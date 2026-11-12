---
title: "Source provenance"
description: "REST endpoints tagged source-provenance: 1 operation."
sidebar_position: 94
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.544.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `source-provenance` · 1 operation

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/provenance` {#get-source-provenance-v1-versions-tenant-slug-project-id-version-record-id-provenance-get}

**Get the source provenance of a revision's paths, operations and components**

For every path, operation and component: `imported` (unchanged since the import), `source-edited` (changed through a source apply since) or `local` (changed or created in Apiome), keyed by JSON Pointer with the class or path id where one exists, plus the imported file and its digest. A draft is measured against its nearest ancestor's import.

`?pointer=` returns only the element that owns that pointer, with an excerpt of the original import text (at most 40 lines).

Requires `projects:view`.

Operation id: `get_source_provenance_v1_versions__tenant_slug___project_id___version_record_id__provenance_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `pointer` | query | string or null | no | Narrow to the element owning this JSON Pointer. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the source provenance of a revision's paths, operations and components. | `application/json` [`SourceProvenanceResponse`](#schema-sourceprovenanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SourceProvenanceResponse` {#schema-sourceprovenanceresponse}

A revision's source provenance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versionRecordId` | string | yes | Version Record ID. |
| `snapshot` | `ImportSnapshotOut` or null | no | Null when no import in the revision's lineage was recorded: every element then reads `local`, except those a source apply changed. |
| `elements` | array of `ElementProvenanceOut` | yes | Elements. |
| `preserved` | array of `PreservedProvenanceOut` | yes | Preserved. |
| `counts` | map of integer | yes | Elements per status. |
