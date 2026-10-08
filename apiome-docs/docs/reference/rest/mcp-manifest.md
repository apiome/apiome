---
title: "MCP manifest"
description: "REST endpoints tagged mcp-manifest: 3 operations."
sidebar_position: 35
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-manifest` · 3 operations

## `POST /v1/mcp/{tenant_slug}/endpoints/manifest-import` {#import-mcp-manifest-v1-mcp-tenant-slug-endpoints-manifest-import-post}

**Catalog an MCP server from a static manifest**

Import a static MCP server descriptor — tools, resources, resource templates and prompts with their JSON Schemas — without probing the server (FMT-1.7). The declared surface is normalized and fingerprinted by the same code a live discovery uses, so it is directly comparable with an observed one.

**Never creates a duplicate.** When the manifest names a server the catalog already holds — by normalized endpoint URL, or by an identical declared surface fingerprint — the declaration attaches to that endpoint. Only an unrecognised server registers a new one, stamped `added_via: import`.

A declaration is *not* a version snapshot: it never becomes `current_version_id` and never appears in the change feed. Where a manifest and a probe disagree, both values are kept and reported by the surface-provenance report.

Operation id: `import_mcp_manifest_v1_mcp__tenant_slug__endpoints_manifest_import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for catalog an mcp server from a static manifest.

- `application/json` — [`McpManifestImportRequest`](#schema-mcpmanifestimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for catalog an mcp server from a static manifest. | `application/json` [`McpManifestImportResponse`](#schema-mcpmanifestimportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/manifests` {#list-mcp-endpoint-manifests-v1-mcp-tenant-slug-endpoints-endpoint-id-manifests-get}

**List an endpoint's declared manifests**

Every static manifest attached to this endpoint, newest first (FMT-1.7). Superseded declarations are excluded unless `include_retired` is set — they stay readable so an attribution made against one remains interpretable.

Operation id: `list_mcp_endpoint_manifests_v1_mcp__tenant_slug__endpoints__endpoint_id__manifests_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `include_retired` | query | boolean | no | Include superseded declarations. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list an endpoint's declared manifests. | `application/json` [`McpDeclaredManifestListResponse`](#schema-mcpdeclaredmanifestlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/surface-provenance` {#get-mcp-surface-provenance-v1-mcp-tenant-slug-endpoints-endpoint-id-surface-provenance-get}

**Attribute an endpoint's surface facts to declared / observed sources**

For every fact on this endpoint's surface — protocol version, server identity, declared capabilities, and each tool / resource / resource template / prompt — say whether it came from a **declared** manifest, an **observed** probe, or **both** (FMT-1.7).

Where both carry a fact and their values differ, the fact reads `conflicts` and both values are returned; nothing here picks a winner. An endpoint with no manifest reads as `observed_only`, never as agreement.

Operation id: `get_mcp_surface_provenance_v1_mcp__tenant_slug__endpoints__endpoint_id__surface_provenance_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for attribute an endpoint's surface facts to declared / observed sources. | `application/json` [`McpSurfaceProvenanceResponse`](#schema-mcpsurfaceprovenanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `McpDeclaredManifestListResponse` {#schema-mcpdeclaredmanifestlistresponse}

Every declaration attached to one endpoint.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Always true for a 2xx response. |
| `manifests` | array of `McpDeclaredManifestOut` | no | Declarations, newest first. |

### `McpManifestImportRequest` {#schema-mcpmanifestimportrequest}

A static MCP server manifest to catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `manifest` | string | yes | The manifest document as text (JSON). The same bytes the `mcp` import adapter accepts. |
| `endpoint_url` | string or null | no | Where this server is reached, overriding the manifest's `transport` block. Required when the manifest declares no transport. |
| `transport` | string or null | no | Transport override: `streamable_http`, `sse`, or `stdio`. Defaults to the manifest's declared transport. |
| `source_label` | string or null | no | Where the manifest came from (filename / URL). Recorded, never fetched. |

### `McpManifestImportResponse` {#schema-mcpmanifestimportresponse}

The outcome of cataloguing a server from a manifest.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Always true for a 2xx response. |
| `endpoint` | `McpEndpointOut` | yes | The endpoint the manifest now describes. |
| `manifest` | `McpDeclaredManifestOut` | yes | The declaration that was attached. |
| `endpoint_created` | boolean | yes | True when no catalogued endpoint matched and one was registered. |
| `match` | string | yes | How the endpoint was recognised: `address` (same normalized endpoint URL), `surface` (same declared surface fingerprint), or `none` (created). |
| `surface_conflict` | boolean | yes | True when the endpoint has been probed and its observed surface fingerprint differs from the declared one. Not an error — see the surface-provenance report. |
| `observed_fingerprint` | string or null | no | The endpoint's current observed surface fingerprint, if any. |
| `superseded_manifests` | integer | no | How many earlier declarations this import retired. |
| `reason` | string | yes | One sentence explaining where the manifest landed and why. |

### `McpSurfaceProvenanceResponse` {#schema-mcpsurfaceprovenanceresponse}

The declared-vs-observed attribution for one endpoint's surface.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Always true for a 2xx response. |
| `endpoint_id` | string | yes | The endpoint the report describes. |
| `surface_match` | string | yes | `none`, `declared_only`, `observed_only`, `identical` (the two fingerprints agree), or `divergent`. |
| `declared_fingerprint` | string or null | no | The declared surface's fingerprint, when one is attached. |
| `observed_fingerprint` | string or null | no | The observed surface's fingerprint, when discovery has run. |
| `fingerprints_match` | boolean | yes | True only when both surfaces exist and fingerprint identically. |
| `origin_counts` | map of integer | no | Fact count per origin. |
| `conflict_count` | integer | yes | How many facts the two sources disagree on. |
| `facts` | array of `McpSurfaceFactOut` | no | Every attributable fact, identity first then items. |
