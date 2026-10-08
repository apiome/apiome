---
title: "Agent outputs"
description: "REST endpoints tagged agent-outputs: 1 operation."
sidebar_position: 5
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `agent-outputs` · 1 operation

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/agent-outputs` {#get-version-agent-outputs-v1-versions-tenant-slug-project-id-version-record-id-agent-outputs-get}

**Get Version Agent Outputs**

Return the deterministic agent outputs for one published revision.

Resolves the project and version within the caller's tenant, requires the revision to
be published, loads its approved canonical content, applies the portal's public/private
policy, and renders the requested output with a content-addressed ``ETag`` and
``Cache-Control``. A matching ``If-None-Match`` short-circuits to ``304``.

Operation id: `get_version_agent_outputs_v1_versions__tenant_slug___project_id___version_record_id__agent_outputs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `output` | query | string or null | no | Which output to return: omit (or 'index') for the JSON index, or 'llms.txt' / 'robots.txt' / 'catalog' / 'release' for one raw output. |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version agent outputs. | `application/json` any |
| 304 | Not modified (ETag matched If-None-Match). | — |
| 400 | Malformed project id, unknown output, or unpublished revision. | — |
| 404 | Project or version not found in tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
