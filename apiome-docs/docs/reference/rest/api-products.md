---
title: "API products"
description: "REST endpoints tagged api-products: 8 operations."
sidebar_position: 10
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.588.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `api-products` · 8 operations

## `GET /v1/tenants/{tenant_slug}/products` {#list-tenant-products-v1-tenants-tenant-slug-products-get}

**List API products**

Every live API product of the tenant, by name, with its owner team, visibility, state and member count. Deleted products are not listed.

Requires `projects:view`.

Operation id: `list_tenant_products_v1_tenants__tenant_slug__products_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list api products. | `application/json` [`ApiProductListResponse`](#schema-apiproductlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/products` {#create-tenant-product-v1-tenants-tenant-slug-products-post}

**Create an API product**

Create an API product, optionally with its first members. The `slug` is derived from `name` when omitted and cannot be changed afterwards. `owner_team` is a team slug. `visibility` is `private` (default), `workspace` or `portal`; a `portal` product needs every member published (`api-product-portal-unpublished`, 422, with `blockers`). `state` is `draft` (default), `published`, `deprecated` or `retired`.

Audited as `api_product.create`. Requires `projects:create`.

Operation id: `create_tenant_product_v1_tenants__tenant_slug__products_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create an api product.

- `application/json` — [`ApiProductInput`](#schema-apiproductinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create an api product. | `application/json` [`ApiProductRecord`](#schema-apiproductrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/products/{product_slug}` {#read-tenant-product-v1-tenants-tenant-slug-products-product-slug-get}

**Read an API product**

One live API product with its members, each resolved to its entity and — for a Project member — the version it means today: a `project_latest` member follows every new publish. `portal_ready` is true when every member is published.

Requires `projects:view`.

Operation id: `read_tenant_product_v1_tenants__tenant_slug__products__product_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an api product. | `application/json` [`ApiProductRecord`](#schema-apiproductrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/products/{product_slug}` {#patch-tenant-product-v1-tenants-tenant-slug-products-product-slug-patch}

**Update an API product**

Change a product's name, summary, owner team, visibility or state. Omitted fields are left alone; `null` clears `summary` or `owner_team`. The slug is not updatable. Setting `visibility` to `portal` is refused while a member is unpublished.

Audited as `api_product.update`. Requires `projects:edit`.

Operation id: `patch_tenant_product_v1_tenants__tenant_slug__products__product_slug__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update an api product.

- `application/json` — [`ApiProductPatch`](#schema-apiproductpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update an api product. | `application/json` [`ApiProductRecord`](#schema-apiproductrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/products/{product_slug}` {#delete-tenant-product-v1-tenants-tenant-slug-products-product-slug-delete}

**Delete an API product**

Soft-delete a product; its slug is free again and its `includes` edges leave the dependency graph. The Projects and MCP servers it bundled are untouched.

Audited as `api_product.delete`. Requires `projects:delete`.

Operation id: `delete_tenant_product_v1_tenants__tenant_slug__products__product_slug__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete an api product. | `application/json` [`ApiProductDeleteResponse`](#schema-apiproductdeleteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/products/{product_slug}/members` {#list-tenant-product-members-v1-tenants-tenant-slug-products-product-slug-members-get}

**List an API product's members**

The product's members, each resolved to its entity and (for a Project) the version it means today, with whether it is published.

Requires `projects:view`.

Operation id: `list_tenant_product_members_v1_tenants__tenant_slug__products__product_slug__members_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list an api product's members. | `application/json` [`ApiProductMemberListResponse`](#schema-apiproductmemberlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/products/{product_slug}/members` {#add-tenant-product-member-v1-tenants-tenant-slug-products-product-slug-members-post}

**Add a member to an API product**

Include a Project (`project_latest`, or `project_version` with a `version` label or a `2.x` range), an MCP server (`mcp_server`) or a catalog item (`catalog_item`), by id or slug, optionally in one `environment`. Adding an unpublished member to a `portal` product is refused (422, with `blockers`).

Audited as `api_product.member.add`. Requires `projects:edit`.

Operation id: `add_tenant_product_member_v1_tenants__tenant_slug__products__product_slug__members_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add a member to an api product.

- `application/json` — [`ApiProductMemberInput`](#schema-apiproductmemberinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for add a member to an api product. | `application/json` [`ApiProductRecord`](#schema-apiproductrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/products/{product_slug}/members/{member_id}` {#remove-tenant-product-member-v1-tenants-tenant-slug-products-product-slug-members-member-id-delete}

**Remove a member from an API product**

Remove one member by its id (from the product's `members`). The entity itself is untouched.

Audited as `api_product.member.remove`. Requires `projects:edit`.

Operation id: `remove_tenant_product_member_v1_tenants__tenant_slug__products__product_slug__members__member_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `member_id` | path | string | yes | Tenant member identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove a member from an api product. | `application/json` [`ApiProductRecord`](#schema-apiproductrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ApiProductDeleteResponse` {#schema-apiproductdeleteresponse}

What a delete did.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | The deleted product's slug (now free for reuse). |

### `ApiProductInput` {#schema-apiproductinput}

A product to create.

Attributes:
    slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
    name: The display name.
    summary: What the product is, in a sentence or two.
    owner_team: The owning team's slug.
    visibility: ``private`` (default), ``workspace`` or ``portal``.
    state: ``draft`` (default), ``published``, ``deprecated`` or ``retired``.
    members: Members to include from the start.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `owner_team` | string or null | no | The owning team's slug. |
| `visibility` | enum `"private"`, `"workspace"`, `"portal"` | no | Visibility. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` | no | State. |
| `members` | array of [`ApiProductMemberInput`](#schema-apiproductmemberinput) | no | Members. |

### `ApiProductListResponse` {#schema-apiproductlistresponse}

Every live product of the tenant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `products` | array of [`ApiProductRecord`](#schema-apiproductrecord) | no | The products, by name. |
| `count` | integer | yes | How many products were returned. |

### `ApiProductMemberInput` {#schema-apiproductmemberinput}

One member to add.

Attributes:
    kind: The member kind.
    ref: The member's id, or its slug (a Project, catalog item or MCP server slug).
    version: For ``project_version`` only: a version label or a ``2.x`` range.
    environment: Narrows the member to one environment (``production``); empty for all.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"project_latest"`, `"project_version"`, `"mcp_server"`, `"catalog_item"` | yes | Kind. |
| `ref` | string | yes | Ref. |
| `version` | string or null | no | Version. |
| `environment` | string or null | no | Environment. |

### `ApiProductMemberListResponse` {#schema-apiproductmemberlistresponse}

A product's members.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `members` | array of `ApiProductMember` | no | Members. |
| `count` | integer | yes | Number of count. |

### `ApiProductPatch` {#schema-apiproductpatch}

A partial update. Omitted fields are left alone; ``null`` clears ``summary`` or ``owner_team``.

The slug is deliberately absent: it is the handle URLs and plans name. Members change through
the members sub-resource.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `owner_team` | string or null | no | Owner Team. |
| `visibility` | enum `"private"`, `"workspace"`, `"portal"` or null | no | Visibility. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` or null | no | State. |

### `ApiProductRecord` {#schema-apiproductrecord}

A stored product.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `owner_team` | `OwnerTeam` or null | no | Owner Team. |
| `visibility` | enum `"private"`, `"workspace"`, `"portal"` | yes | Visibility. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` | yes | State. |
| `member_count` | integer | no | How many members the product has. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `members` | array of `ApiProductMember` or null | no | The members; present on single-product reads and writes. |
| `portal_ready` | boolean or null | no | Present with `members`: true when every member is published, so `portal` is allowed. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
