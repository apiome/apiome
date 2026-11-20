---
title: "Arazzo workflows"
description: "REST endpoints tagged arazzo-workflows: 8 operations."
sidebar_position: 11
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.611.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `arazzo-workflows` · 8 operations

## `GET /v1/workflows/{tenant_slug}/catalog/{item_id}` {#list-catalog-item-workflows-v1-workflows-tenant-slug-catalog-item-id-get}

**List Catalog Item Workflows**

List the Arazzo workflows of a catalog item's latest revision.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item UUID.
    auth_data: Authentication data (injected by dependency).

Returns:
    The latest revision's workflows; ``version_id`` is null and ``workflows`` empty when the
    item has no revisions yet.

Raises:
    HTTPException: 400 for a malformed id; 404 when the id is not a catalog item in this
        tenant (a publishable Project is read through the versions route instead).

Operation id: `list_catalog_item_workflows_v1_workflows__tenant_slug__catalog__item_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list catalog item workflows. | `application/json` [`ArazzoWorkflowsResponse`](#schema-arazzoworkflowsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/catalog/{item_id}/revisions/{version_id}` {#list-catalog-revision-workflows-v1-workflows-tenant-slug-catalog-item-id-revisions-version-id-get}

**List Catalog Revision Workflows**

List the Arazzo workflows of one revision of a catalog item.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item UUID.
    version_id: The revision (``versions.id``) UUID; it must belong to ``item_id``.
    auth_data: Authentication data (injected by dependency).

Returns:
    That revision's workflows, shaped like the latest-revision read.

Raises:
    HTTPException: 400 for a malformed id; 404 when the id is not a catalog item in this
        tenant, or the revision is not one of its revisions.

Operation id: `list_catalog_revision_workflows_v1_workflows__tenant_slug__catalog__item_id__revisions__version_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list catalog revision workflows. | `application/json` [`ArazzoWorkflowsResponse`](#schema-arazzoworkflowsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/operations/{path_operation_id}` {#get-workflow-step-operation-v1-workflows-tenant-slug-operations-path-operation-id-get}

**Get Workflow Step Operation**

Read the operation an Arazzo step calls, for the step drawer.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    path_operation_id: The ``path_operation.id`` a step resolved to.
    auth_data: Authentication data (injected by dependency).

Returns:
    The operation's method, route, summary, owning project and revision, parameters and
    declared responses.

Raises:
    HTTPException: 400 for a malformed id; 404 when the operation is not in this tenant.

Operation id: `get_workflow_step_operation_v1_workflows__tenant_slug__operations__path_operation_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `path_operation_id` | path | string | yes | Path parameter identifying the path operation id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get workflow step operation. | `application/json` [`ArazzoOperationDetailOut`](#schema-arazzooperationdetailout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/versions/{version_id}` {#list-version-workflows-v1-workflows-tenant-slug-versions-version-id-get}

**List Version Workflows**

List the Arazzo workflows persisted for a revision.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    version_id: The revision (``versions.id``) UUID.
    auth_data: Authentication data (injected by dependency).

Returns:
    The revision's workflows in declaration order, each with its ordered steps, the
    operation each step resolved to, and its source-description status. An empty
    ``workflows`` list means the revision holds no Arazzo document.

Raises:
    HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant.

Operation id: `list_version_workflows_v1_workflows__tenant_slug__versions__version_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list version workflows. | `application/json` [`ArazzoWorkflowsResponse`](#schema-arazzoworkflowsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}` {#get-version-workflow-v1-workflows-tenant-slug-versions-version-id-workflows-workflow-id-get}

**Get Version Workflow**

Read one persisted Arazzo workflow of a revision.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    version_id: The revision (``versions.id``) UUID.
    workflow_id: The workflow's Arazzo ``workflowId``.
    auth_data: Authentication data (injected by dependency).

Returns:
    The workflow with its ordered steps and their resolution state, plus every source the
    document declares.

Raises:
    HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant or
        has no such workflow.

Operation id: `get_version_workflow_v1_workflows__tenant_slug__versions__version_id__workflows__workflow_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `workflow_id` | path | string | yes | Path parameter identifying the workflow id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version workflow. | `application/json` [`ArazzoWorkflowDetailResponse`](#schema-arazzoworkflowdetailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/run` {#run-version-workflow-v1-workflows-tenant-slug-versions-version-id-workflows-workflow-id-run-post}

**Run an Arazzo workflow against a verification target**

Execute one stored workflow end to end against an ECA-1.2 verification target (a deployment, or a `mock` environment target): steps run in order, each request built from the workflow `inputs` and earlier steps' `outputs` through runtime expressions; each step's `successCriteria` are judged as assertions with expected-vs-actual values; `onSuccess` / `onFailure` `end`, `goto` and `retry` actions are followed.

**Safe by default (CTG-4.3).** A step that sends `POST`/`PUT`/`PATCH`/`DELETE` runs only when the target policy allows mutating methods, `verification.allow_mutating` is set **and** a fixture names the step's operation (or the step, by `case_id`). Otherwise the run is refused before anything is sent: **200** with `ok: false` and every reason in `refusals` (also used for unresolved steps, nested-workflow steps and inputs that fail the workflow's `inputs` schema).

An executed run is recorded as immutable ECA-1.3 evidence (**201**; **200** on an idempotent replay) whatever its outcome. 404 when the revision or workflow is unknown; target faults are 400/404; evidence faults are 400.

Operation id: `run_version_workflow_v1_workflows__tenant_slug__versions__version_id__workflows__workflow_id__run_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `workflow_id` | path | string | yes | Path parameter identifying the workflow id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for run an arazzo workflow against a verification target.

- `application/json` — [`ArazzoWorkflowRunRequest`](#schema-arazzoworkflowrunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run an arazzo workflow against a verification target. | `application/json` [`ArazzoWorkflowRunResponse`](#schema-arazzoworkflowrunresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps` {#list-version-workflow-steps-v1-workflows-tenant-slug-versions-version-id-workflows-workflow-id-steps-get}

**List Version Workflow Steps**

List the steps of one persisted Arazzo workflow, in source order.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    version_id: The revision (``versions.id``) UUID.
    workflow_id: The workflow's Arazzo ``workflowId``.
    auth_data: Authentication data (injected by dependency).

Returns:
    The ordered steps, each with its ``operationRef`` / ``operationId``, resolution state and
    resolved operation, and the steps counted by resolution state.

Raises:
    HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant or
        has no such workflow.

Operation id: `list_version_workflow_steps_v1_workflows__tenant_slug__versions__version_id__workflows__workflow_id__steps_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `workflow_id` | path | string | yes | Path parameter identifying the workflow id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list version workflow steps. | `application/json` [`ArazzoWorkflowStepsResponse`](#schema-arazzoworkflowstepsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps/{step_id}` {#get-version-workflow-step-v1-workflows-tenant-slug-versions-version-id-workflows-workflow-id-steps-step-id-get}

**Get Version Workflow Step**

Read one step of a persisted Arazzo workflow.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    version_id: The revision (``versions.id``) UUID.
    workflow_id: The workflow's Arazzo ``workflowId``.
    step_id: The step's Arazzo ``stepId``.
    auth_data: Authentication data (injected by dependency).

Returns:
    The step with its target, resolution state, resolved operation and actions.

Raises:
    HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant, or
        has no such workflow or step.

Operation id: `get_version_workflow_step_v1_workflows__tenant_slug__versions__version_id__workflows__workflow_id__steps__step_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `workflow_id` | path | string | yes | Path parameter identifying the workflow id segment. |
| `step_id` | path | string | yes | Path parameter identifying the step id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version workflow step. | `application/json` [`ArazzoWorkflowStepOut`](#schema-arazzoworkflowstepout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ArazzoOperationDetailOut` {#schema-arazzooperationdetailout}

One path operation with its parameters and responses (the step drawer).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `path_operation_id` | string | yes | `path_operation.id` the step targets |
| `method` | string | yes | Upper-case HTTP method |
| `path` | string | yes | Route template, e.g. `/pets/{petId}` |
| `path_id` | string | yes | `version_path.id` holding the route |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `description` | string or null | no | Free-text description. |
| `operation_id` | string or null | no | The operation's `operationId`, if any |
| `version_id` | string | yes | Revision (`versions.id`) holding the operation |
| `version_label` | string or null | no | Display version string of that revision |
| `project_id` | string | yes | Project or catalog item holding the operation |
| `project_name` | string or null | no | Project Name. |
| `project_publishable` | boolean | no | True for a Project, false for a catalog item |
| `parameters` | array of `ArazzoOperationParameterOut` | no | Parameters. |
| `responses` | array of `ArazzoOperationResponseOut` | no | Responses. |

### `ArazzoWorkflowDetailResponse` {#schema-arazzoworkflowdetailresponse}

One persisted Arazzo workflow of a revision, with the revision it was read from.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | The revision read |
| `project_id` | string | yes | Project or catalog item owning the revision |
| `sources` | array of `ArazzoSourceDescriptionOut` | no | Every source the document declares |
| `workflow` | `ArazzoWorkflowOut` | yes | Workflow. |

### `ArazzoWorkflowRunRequest` {#schema-arazzoworkflowrunrequest}

Which target to run a workflow against, with what inputs, and how much it may touch.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | Verification target slug or id (ECA-1.2) — a deployment, or a `mock` environment target pointing at an Apiome mock. |
| `inputs` | object | no | Workflow inputs (`$inputs.…`). Checked against the workflow's `inputs` schema after its property defaults are applied. The run hashes them into the digest and does not store them; a criterion that compares with an input quotes its value as evidence. |
| `verification` | `ArazzoRunOptions` | no | What the run may send. Safe methods only by default; a mutating step needs the target policy, `allow_mutating` and a fixture naming its operation. |
| `idempotency_key` | string or null | no | Evidence retry key; forwarded to the verification-runs store. |
| `context` | object | no | Non-secret CI context (commit, branch, workflow URL). Never credentials. |

### `ArazzoWorkflowRunResponse` {#schema-arazzoworkflowrunresponse}

The outcome of one workflow run attempt.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the workflow executed (whatever its outcome). |
| `version_id` | string | yes | The revision the workflow was read from. |
| `workflow_id` | string | yes | The workflow's `workflowId`. |
| `digest` | string or null | no | Digest of the compiled run plan and its inputs. |
| `report` | `ArazzoWorkflowRunReport` or null | no | The per-step report when `ok` is true. |
| `refusals` | array of `ArazzoRunRefusal` | no | Everything that kept the run from starting; nothing was sent when non-empty. |
| `fixture_findings` | array of `FixtureFinding` | no | Fixtures that matched no mutating step. |
| `run` | `VerificationRunRecord` or null | no | The immutable ECA-1.3 evidence behind the report. |
| `created` | boolean or null | no | True when evidence was newly written; False on replay. |
| `error` | `ArazzoRunErrorOut` or null | no | Populated when `ok` is false. |

### `ArazzoWorkflowStepOut` {#schema-arazzoworkflowstepout}

One step of a workflow, in source order, with what it calls and where it goes next.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `step_id` | string | yes | Step ID. |
| `order_index` | integer | yes | Order Index. |
| `description` | string or null | no | Free-text description. |
| `target_kind` | enum `"operation"`, `"workflow"`, `"none"` | yes | Whether the step calls an operation, another workflow, or nothing |
| `target_workflow_id` | string or null | no | Called `workflowId`, if any |
| `operation_ref` | string or null | no | Raw `operationRef` / `operationPath` |
| `operation_id` | string or null | no | Raw `operationId` |
| `resolution_status` | string | yes | `resolved`, `unresolved`, `not_applicable` or `parse_error` |
| `resolution_reason` | string or null | no | Resolution Reason. |
| `operation` | `ArazzoStepOperationOut` or null | no | The resolved operation; null when unresolved or since deleted |
| `source_names` | array of string | no | Declared sources the step's target points into |
| `parameters` | array of any | no | Parameters. |
| `request_body` | any or null | no | Request Body. |
| `success_criteria` | array of any | no | Success Criteria. |
| `on_success` | array of any | no | `onSuccess` actions, verbatim |
| `on_failure` | array of any | no | `onFailure` actions, verbatim |
| `outputs` | object | no | Outputs. |
| `depends_on` | array of any | no | Depends On. |

### `ArazzoWorkflowStepsResponse` {#schema-arazzoworkflowstepsresponse}

The ordered steps of one persisted Arazzo workflow.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | The revision read |
| `workflow_id` | string | yes | The Arazzo `workflowId` the steps belong to |
| `step_resolution` | map of integer | no | Steps counted by `resolution_status` |
| `steps` | array of [`ArazzoWorkflowStepOut`](#schema-arazzoworkflowstepout) | no | Steps. |

### `ArazzoWorkflowsResponse` {#schema-arazzoworkflowsresponse}

The Arazzo workflows persisted for one revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string or null | no | The revision read; null for a catalog item with no revisions |
| `project_id` | string or null | no | Project identifier the resource belongs to. |
| `sources` | array of `ArazzoSourceDescriptionOut` | no | Every source the document declares |
| `workflows` | array of `ArazzoWorkflowOut` | no | Workflows. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
