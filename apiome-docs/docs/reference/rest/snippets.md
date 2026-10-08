---
title: "Snippets"
description: "REST endpoints tagged snippets: 1 operation."
sidebar_position: 67
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `snippets` · 1 operation

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/snippets/{operation_id}` {#get-version-operation-snippet-v1-versions-tenant-slug-project-id-version-record-id-snippets-operation-id-get}

**Render a usage snippet for one operation of a published revision**

Return the install + call snippet for one operation of a published revision.

Resolves the project and version within the caller's tenant, requires the revision to
be published, loads its canonical content, addresses the operation by operationId /
name / URL-encoded canonical key, and renders the requested language deterministically
with a content-addressed ``ETag``. A matching ``If-None-Match`` short-circuits to 304.

Args:
    tenant_slug: The tenant's slug. The token's tenant still scopes every read; the slug is
        used only to resolve ``{tenant}`` in the tenant's branding patterns.
    project_id: The project UUID within the tenant.
    version_record_id: The revision UUID (``versions.id``).
    operation_id: operationId, canonical name, or URL-encoded canonical key.
    lang: ``ts`` / ``python`` / ``curl`` (aliases ``fetch`` / ``httpx``).
    if_none_match: Standard conditional-request header.
    auth_data: The authenticated tenant context (JWT or API key).

Returns:
    The :class:`SnippetResponse` JSON, or an empty 304.

Operation id: `get_version_operation_snippet_v1_versions__tenant_slug___project_id___version_record_id__snippets__operation_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `lang` | query | string | yes | Snippet language: ts \| python \| curl (aliases: fetch → ts, httpx → python). |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for render a usage snippet for one operation of a published revision. | `application/json` any |
| 304 | Not modified (ETag matched If-None-Match). | — |
| 400 | Malformed project id, unknown lang, or unpublished revision. | — |
| 404 | Project, version, or operation not found in tenant. | — |
| 422 | The operation has no HTTP binding (no snippet is defined). | — |
