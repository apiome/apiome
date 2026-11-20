---
title: "Arazzo workflows"
description: "REST endpoints tagged arazzo-workflows: 3 operations."
sidebar_position: 11
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.601.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `arazzo-workflows` · 3 operations

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
