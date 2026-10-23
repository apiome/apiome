---
title: "Project repository sources"
description: "REST endpoints tagged project-repository-sources: 1 operation."
sidebar_position: 59
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.296.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `project-repository-sources` · 1 operation

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources` {#list-project-repository-sources-v1-tenants-tenant-slug-projects-project-ref-repository-sources-get}

**List a project's contributing repositories and per-entity provenance**

The repository files whose imports make up the project's merged API surface, in precedence order (1 contributed first), and every class and path of one version with the file that defined it. `source` is null for a class or path no repository defined (edited in Apiome, or imported before multi-repository merge).

`version` is a revision id or version label; the project's newest version when omitted.

Requires `projects:view`.

Operation id: `list_project_repository_sources_v1_tenants__tenant_slug__projects__project_ref__repository_sources_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Revision id or version label. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's contributing repositories and per-entity provenance. | `application/json` [`ProjectRepositorySourcesResponse`](#schema-projectrepositorysourcesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProjectRepositorySourcesResponse` {#schema-projectrepositorysourcesresponse}

A project's contributing repository files and one version's provenance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `sources` | array of `ProjectRepositorySource` | no | Contributing files in precedence order. |
| `version` | `ProvenanceVersion` or null | no | The version described; null when the project has none. |
| `entities` | array of `EntityProvenance` | no | Every live class (first) and path of the version, each ordered by key. |
| `counts` | `ProvenanceCounts` | yes | Counts. |
