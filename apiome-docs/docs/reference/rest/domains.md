---
title: "Domains"
description: "REST endpoints tagged domains: 6 operations."
sidebar_position: 19
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `domains` · 6 operations

## `PUT /v1/domains/{tenant_slug}/classes/{class_id}` {#assign-class-domain-v1-domains-tenant-slug-classes-class-id-put}

**Assign Class Domain**

Move a class into a domain, or into ``shared/`` with ``domain_id: null``.

Operation id: `assign_class_domain_v1_domains__tenant_slug__classes__class_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for assign class domain.

- `application/json` — [`DomainAssignmentRequest`](#schema-domainassignmentrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign class domain. | `application/json` [`DomainMemberSchema`](#schema-domainmemberschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/domains/{tenant_slug}/paths/{path_id}` {#assign-path-domain-v1-domains-tenant-slug-paths-path-id-put}

**Assign Path Domain**

Move a path into a domain, or into ``shared/`` with ``domain_id: null``.

Operation id: `assign_path_domain_v1_domains__tenant_slug__paths__path_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for assign path domain.

- `application/json` — [`DomainAssignmentRequest`](#schema-domainassignmentrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign path domain. | `application/json` [`DomainMemberSchema`](#schema-domainmemberschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/domains/{tenant_slug}/version/{version_id}` {#list-domains-v1-domains-tenant-slug-version-version-id-get}

**List Domains**

List a version's domain folders in tree order, with ``shared/`` last.

The synthetic ``shared/`` entry is always present, including for a version that has no domains
at all — where it is the whole tree.

Operation id: `list_domains_v1_domains__tenant_slug__version__version_id__get`

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
| 200 | Successful response for list domains. | `application/json` array of [`DomainSchema`](#schema-domainschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/domains/{tenant_slug}/version/{version_id}` {#create-domain-v1-domains-tenant-slug-version-version-id-post}

**Create Domain**

Create a domain folder in a version.

Operation id: `create_domain_v1_domains__tenant_slug__version__version_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create domain.

- `application/json` — [`DomainCreateRequest`](#schema-domaincreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create domain. | `application/json` [`DomainSchema`](#schema-domainschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/domains/{tenant_slug}/{domain_id}` {#update-domain-v1-domains-tenant-slug-domain-id-patch}

**Update Domain**

Rename or reorder a domain folder.

Operation id: `update_domain_v1_domains__tenant_slug___domain_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update domain.

- `application/json` — [`DomainUpdateRequest`](#schema-domainupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update domain. | `application/json` [`DomainSchema`](#schema-domainschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/domains/{tenant_slug}/{domain_id}` {#delete-domain-v1-domains-tenant-slug-domain-id-delete}

**Delete Domain**

Delete a domain folder, moving its classes and paths to ``shared/``.

Returns the number of members released, so the caller can report what moved rather than
asserting that nothing was lost.

Operation id: `delete_domain_v1_domains__tenant_slug___domain_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `domain_id` | path | string | yes | Path parameter identifying the domain id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete domain. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DomainAssignmentRequest` {#schema-domainassignmentrequest}

Request model for moving a class or path between domains.

``domain_id`` is a domain UUID, the literal ``"shared"``, or null — the last two both meaning
the derived bucket. It is required rather than optional so that omitting it is a validation
error instead of a silent move to ``shared/``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain_id` | string or null | yes | Domain ID. |

### `DomainCreateRequest` {#schema-domaincreaterequest}

Request model for creating a domain folder.

``slug`` is derived from ``name`` when omitted, so the common case is a single field.
``sort_order`` defaults to the end of the tree.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `sort_order` | integer or null | no | Sort Order. |

### `DomainMemberSchema` {#schema-domainmemberschema}

A class or path with its current domain membership.

``name`` carries the class name or the pathname, whichever the member is, so one shape answers
both move endpoints.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Human-readable name. |
| `domain_id` | string or null | no | Domain ID. |
| `kind` | string | yes | Kind. |

### `DomainSchema` {#schema-domainschema}

A domain folder grouping a version's classes and paths (DUW-1.1).

``id`` is None for exactly one entry per version: the derived ``shared/`` bucket, which
collects members with no domain. A client must read ``virtual`` rather than inferring
editability from the name, since a real domain may legitimately be called anything else.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string or null | no | Stable resource identifier. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Human-readable name. |
| `slug` | string | yes | URL-safe identifier. |
| `sort_order` | integer | no | Sort Order. |
| `virtual` | boolean | no | Virtual. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |

### `DomainUpdateRequest` {#schema-domainupdaterequest}

Request model for renaming or reordering a domain.

Every field is optional and only the supplied ones are written; renaming a domain never moves
it in the tree unless ``sort_order`` is given too.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `sort_order` | integer or null | no | Sort Order. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
