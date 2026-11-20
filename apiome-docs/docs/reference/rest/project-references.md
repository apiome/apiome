---
title: "Project references"
description: "REST endpoints tagged project-references: 6 operations."
sidebar_position: 76
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.611.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `project-references` · 6 operations

## `GET /v1/projects/{tenant_slug}/{project_id}/references` {#list-project-references-v1-projects-tenant-slug-project-id-references-get}

**List a version's external $refs and cycles**

List a version's external references, their last refresh and pin, and its `$ref` cycles.

Raises:
    HTTPException: 404 unknown project / version; 409 when the version has no single-document
        source (``unsupported-source``, ``source-withheld``, ``no-source``); 422 unparseable.

Operation id: `list_project_references_v1_projects__tenant_slug___project_id__references_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version` | query | string or null | no | Version id or label; default the latest. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a version's external $refs and cycles. | `application/json` [`ProjectReferencesOut`](#schema-projectreferencesout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_id}/references/pin` {#pin-project-reference-v1-projects-tenant-slug-project-id-references-pin-put}

**Pin an external $ref's last fetched snapshot**

Accept the reference's last fetched snapshot; later refreshes compare against it.

Raises:
    HTTPException: 409 ``ref-not-fetched`` when the reference has no fetched snapshot yet.

Operation id: `pin_project_reference_v1_projects__tenant_slug___project_id__references_pin_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for pin an external $ref's last fetched snapshot.

- `application/json` — [`PinRequest`](#schema-pinrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for pin an external $ref's last fetched snapshot. | `application/json` [`ProjectReference`](#schema-projectreference) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/projects/{tenant_slug}/{project_id}/references/pin` {#unpin-project-reference-v1-projects-tenant-slug-project-id-references-pin-delete}

**Unpin an external $ref**

Remove a reference's pin.

Raises:
    HTTPException: 404 ``ref-not-found`` when the reference was never refreshed.

Operation id: `unpin_project_reference_v1_projects__tenant_slug___project_id__references_pin_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `url` | query | string | yes | Required. Query parameter: url. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unpin an external $ref. | `application/json` [`ProjectReference`](#schema-projectreference) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/projects/{tenant_slug}/{project_id}/references/refresh` {#refresh-project-references-v1-projects-tenant-slug-project-id-references-refresh-post}

**Refresh a version's external $refs**

Fetch the version's external references now and report what changed.

Raises:
    HTTPException: as :func:`list_project_references`; 422 ``unknown-reference`` when ``urls``
        names a URL the version does not reference.

Operation id: `refresh_project_references_v1_projects__tenant_slug___project_id__references_refresh_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for refresh a version's external $refs.

- `application/json` — [`RefreshRequest`](#schema-refreshrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for refresh a version's external $refs. | `application/json` [`ProjectReferencesOut`](#schema-projectreferencesout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/external-ref-policy` {#get-external-ref-policy-v1-tenants-tenant-slug-governance-external-ref-policy-get}

**Get the tenant's external $ref policy**

The external-ref policy in force (``block`` when never set). Readable by any member.

Operation id: `get_external_ref_policy_v1_tenants__tenant_slug__governance_external_ref_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the tenant's external $ref policy. | `application/json` [`ExternalRefPolicyOut`](#schema-externalrefpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/external-ref-policy` {#put-external-ref-policy-v1-tenants-tenant-slug-governance-external-ref-policy-put}

**Set the tenant's external $ref policy**

Change the external-ref policy (tenant administrators only; audit-logged).

Raises:
    HTTPException: 403 for a non-administrator; 422 when an allowlist pattern is not a
        hostname pattern, or ``proxy-fetch`` comes with an empty allowlist.

Operation id: `put_external_ref_policy_v1_tenants__tenant_slug__governance_external_ref_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set the tenant's external $ref policy.

- `application/json` — [`ExternalRefPolicyWrite`](#schema-externalrefpolicywrite)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set the tenant's external $ref policy. | `application/json` [`ExternalRefPolicyOut`](#schema-externalrefpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ExternalRefPolicyOut` {#schema-externalrefpolicyout}

The external-ref policy in force, and whether the caller may change it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"block"`, `"inline"`, `"proxy-fetch"` | yes | `block` fetches nothing; `inline` fetches (only allowlisted hosts when the allowlist is not empty); `proxy-fetch` fetches only allowlisted hosts. |
| `allowlist` | array of string | yes | Hostname patterns: `schemas.acme.com`, `*.acme.com` or `*`. |
| `resolution_allowed` | boolean | yes | The deployment kill switch; false refuses every fetch whatever the mode. |
| `fetches` | boolean | yes | Whether this policy can fetch anything at all. |
| `can_edit` | boolean | yes | Whether the caller is a tenant administrator. |

### `ExternalRefPolicyWrite` {#schema-externalrefpolicywrite}

Body of ``PUT …/governance/external-ref-policy``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"block"`, `"inline"`, `"proxy-fetch"` | yes | Mode. |
| `allowlist` | array of string | no | Allowlist. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PinRequest` {#schema-pinrequest}

Body of ``PUT …/references/pin``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | yes | URL. |

### `ProjectReference` {#schema-projectreference}

One external reference: where it is used and what the last refresh found.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | yes | The URL the reference fetches (fragment removed). |
| `host` | string | yes | Host. |
| `locations` | array of `RefLocation` | yes | Locations. |
| `status` | enum `"not-fetched"`, `"ok"`, `"changed"`, `"unreachable"`, `"blocked"` | yes | `not-fetched` until the first refresh; `changed` when the document differs from its pin (or, unpinned, from the previous fetch). |
| `reason` | string or null | no | Why a fetch was refused or failed. |
| `detail` | string or null | no | Detail. |
| `digest` | string or null | no | sha-256 of the last fetched document. |
| `fetched_at` | string (date-time) or null | no | When the document was last fetched. |
| `checked_at` | string (date-time) or null | no | When the reference was last refreshed. |
| `pinned` | `RefPin` or null | no | Pinned. |
| `diff` | object or null | no | The last change found: `{changes: [{pointer, kind, before?, after?}], total, truncated, against: pin\|previous, from_digest, to_digest}`. |

### `ProjectReferencesOut` {#schema-projectreferencesout}

``GET …/references``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `version_record_id` | string | yes | Version Record ID. |
| `version_label` | string or null | no | Version Label. |
| `references` | array of [`ProjectReference`](#schema-projectreference) | yes | References. |
| `summary` | map of integer | yes | References per status. |
| `cycles` | array of `RefCycle` | yes | Cycles. |
| `cycle_total` | integer | yes | Cycle Total. |
| `cycles_truncated` | boolean | yes | Cycles Truncated. |
| `policy` | [`ExternalRefPolicyOut`](#schema-externalrefpolicyout) | yes | Policy. |
| `refreshed` | integer or null | no | References fetched by this refresh (refresh only). |

### `RefreshRequest` {#schema-refreshrequest}

Body of ``POST …/references/refresh``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string or null | no | Version id or label; default the latest. |
| `urls` | array of string or null | no | Refresh only these URLs (default: every external reference). |
