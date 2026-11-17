---
title: "API products"
description: "REST endpoints tagged api-products: 14 operations."
sidebar_position: 10
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.596.10**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `api-products` · 14 operations

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

Create an API product, optionally with its first members. The `slug` is derived from `name` when omitted and cannot be changed afterwards. `owner_team` is a team slug. `visibility` is `private` (default), `workspace` or `portal`; a `portal` product needs every member published (`api-product-portal-unpublished`, 422, with `blockers`). `state` is `draft` (default) or `published`; anything else is `api-lifecycle-invalid-state` — deprecate and retire with an update.

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

**Lifecycle.** `state` moves draft ⇄ published → deprecated → retired, and deprecated → published reinstates. `retire_at` and `deprecation_message` describe a deprecation and are refused on any other state; a deprecated product appears on the sunset timeline. Retiring is refused before `retire_at` (`api-lifecycle-retire-early`, 409) and while any plan of the product is not retired (`api-product-plans-live`, 409); any other step is `api-lifecycle-transition` (409).

Audited as `api_product.deprecate`, `.reinstate`, `.retire` or `.update`. Requires `projects:edit`.

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

## `GET /v1/tenants/{tenant_slug}/products/{product_slug}/plans` {#list-product-plans-v1-tenants-tenant-slug-products-product-slug-plans-get}

**List an API product's plans**

Every live plan of the product, oldest first, each with its environments resolved to gateway configs, `declared_only` and its notices, and an `api-plan-auth-mismatch` warning per member whose security schemes do not fit the plan's auth strategy.

Requires `projects:view`.

Operation id: `list_product_plans_v1_tenants__tenant_slug__products__product_slug__plans_get`

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
| 200 | Successful response for list an api product's plans. | `application/json` [`ApiPlanListResponse`](#schema-apiplanlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/products/{product_slug}/plans` {#create-product-plan-v1-tenants-tenant-slug-products-product-slug-plans-post}

**Create an API plan**

Add a plan to the product. The `slug` is derived from `name` when omitted and cannot be changed afterwards. `auth_strategy` is `key_auth` (default; `auth_config.header_name`), `oauth2_client_credentials` (`auth_config.idp_config_id`, `auth_config.scopes`), `mtls` or `none`. `limits` is `[{window, requests}]` with `window` one of `second`, `minute`, `hour`, `day`, `month` — every count positive, every window once. `approval` is `manual` (default) or `auto`. `environments` are gateway config slugs or ids; a plan with none, or with one whose connector cannot provision, is saved with `declared_only: true` and an `api-plan-declared-only` notice. `billing_ref` is internal and never exported. A new plan starts as `draft` (default) or `published`; anything else is `api-lifecycle-invalid-state`.

Audited as `api_product.plan.create`. Requires `projects:edit`.

Operation id: `create_product_plan_v1_tenants__tenant_slug__products__product_slug__plans_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create an api plan.

- `application/json` — [`ApiPlanInput`](#schema-apiplaninput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create an api plan. | `application/json` [`ApiPlanRecord`](#schema-apiplanrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/products/{product_slug}/plans/{plan_slug}` {#read-product-plan-v1-tenants-tenant-slug-products-product-slug-plans-plan-slug-get}

**Read an API plan**

One live plan with its environments, `declared_only`, notices and auth warnings.

Requires `projects:view`.

Operation id: `read_product_plan_v1_tenants__tenant_slug__products__product_slug__plans__plan_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `plan_slug` | path | string | yes | Path parameter identifying the plan slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an api plan. | `application/json` [`ApiPlanRecord`](#schema-apiplanrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/products/{product_slug}/plans/{plan_slug}` {#patch-product-plan-v1-tenants-tenant-slug-products-product-slug-plans-plan-slug-patch}

**Update an API plan**

Change any of a plan's fields but its slug. Omitted fields are left alone; `null` clears an optional one. `limits` and `environments` are replaced as a whole; changing `environments` re-derives `declared_only`. Changing `auth_strategy` without `auth_config` re-checks the stored config against the new strategy.

**Lifecycle.** `state` moves draft ⇄ published → deprecated → retired, and deprecated → published reinstates (clearing the deprecation). Deprecating stamps `deprecated_at`, blocks new subscriptions (`accepts_subscriptions: false`) and notifies subscribed application owners once. `retire_at`, `deprecation_message` and `successor` (a published plan of the product with the same auth strategy) describe a deprecation and are refused on any other state. Retiring is refused with `api-lifecycle-retire-early` (409) before `retire_at`, and revokes the plan's provisioning. Any other step is `api-lifecycle-transition` (409); an unusable successor is `api-lifecycle-successor-invalid` (422).

Audited as `api_product.plan.deprecate`, `.reinstate`, `.retire` or `.update`. Requires `projects:edit`.

Operation id: `patch_product_plan_v1_tenants__tenant_slug__products__product_slug__plans__plan_slug__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `plan_slug` | path | string | yes | Path parameter identifying the plan slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update an api plan.

- `application/json` — [`ApiPlanPatch`](#schema-apiplanpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update an api plan. | `application/json` [`ApiPlanRecord`](#schema-apiplanrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/products/{product_slug}/plans/{plan_slug}` {#delete-product-plan-v1-tenants-tenant-slug-products-product-slug-plans-plan-slug-delete}

**Delete an API plan**

Soft-delete a plan; its slug is free again in this product.

Audited as `api_product.plan.delete`. Requires `projects:edit`.

Operation id: `delete_product_plan_v1_tenants__tenant_slug__products__product_slug__plans__plan_slug__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `plan_slug` | path | string | yes | Path parameter identifying the plan slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete an api plan. | `application/json` [`ApiPlanDeleteResponse`](#schema-apiplandeleteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/products/{product_slug}/plans/{plan_slug}/migrate` {#migrate-product-plan-v1-tenants-tenant-slug-products-product-slug-plans-plan-slug-migrate-post}

**Migrate a deprecated plan's subscriptions**

**Migrate to plan.** Moves every subscription of a deprecated plan to `to` — a published plan of the same product with the same auth strategy — re-provisioning each consumer into the target's consumer group (`plan:<product>-<plan>`) with the credential it already holds: `credentials_changed` is always false. The target becomes the plan's `successor`. `dry_run: true` reports what would move and changes nothing.

A plan that is not deprecated is `api-lifecycle-transition` (409); an unknown, unpublished or differently-authenticated target is `api-lifecycle-successor-invalid` (422).

Audited as `api_product.plan.migrate` (not on a dry run). Requires `projects:edit`.

Operation id: `migrate_product_plan_v1_tenants__tenant_slug__products__product_slug__plans__plan_slug__migrate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `product_slug` | path | string | yes | Path parameter identifying the product slug segment. |
| `plan_slug` | path | string | yes | Path parameter identifying the plan slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for migrate a deprecated plan's subscriptions.

- `application/json` — [`ApiPlanMigrateInput`](#schema-apiplanmigrateinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for migrate a deprecated plan's subscriptions. | `application/json` [`ApiPlanMigration`](#schema-apiplanmigration) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ApiPlanDeleteResponse` {#schema-apiplandeleteresponse}

What a delete did.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | The deleted plan's slug (now free for reuse in this product). |

### `ApiPlanInput` {#schema-apiplaninput}

A plan to create.

Attributes:
    slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
    name: The display name (``Standard``).
    description: What the plan offers.
    auth_strategy: How a consumer authenticates; ``key_auth`` by default.
    auth_config: The strategy's settings.
    limits: Declared request limits, at most one per window.
    concurrency: Optional cap on requests in flight.
    approval: ``manual`` (default) or ``auto``.
    environments: Gateway config slugs or ids the plan is provisioned to.
    credential_ttl_days: Optional maximum key age, in days.
    terms_url: The plan's terms (http or https).
    pricing_note: A short note on price, shown to consumers.
    billing_ref: An external billing id; internal only.
    state: ``draft`` (default) or ``published``. A plan is deprecated and retired by an
        update once it exists (:mod:`app.api_lifecycle`).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `auth_strategy` | enum `"key_auth"`, `"oauth2_client_credentials"`, `"mtls"`, `"none"` | no | Auth Strategy. |
| `auth_config` | `PlanAuthConfig` | no | Auth Config. |
| `limits` | array of `PlanLimit` | no | Limits. |
| `concurrency` | integer or null | no | Concurrency. |
| `approval` | enum `"auto"`, `"manual"` | no | Approval. |
| `environments` | array of string | no | Environments. |
| `credential_ttl_days` | integer or null | no | Credential Ttl Days. |
| `terms_url` | string or null | no | Terms URL. |
| `pricing_note` | string or null | no | Pricing Note. |
| `billing_ref` | string or null | no | Billing Ref. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` | no | State. |

### `ApiPlanListResponse` {#schema-apiplanlistresponse}

A product's live plans.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `plans` | array of [`ApiPlanRecord`](#schema-apiplanrecord) | no | The plans, oldest first. |
| `count` | integer | yes | How many plans were returned. |

### `ApiPlanMigrateInput` {#schema-apiplanmigrateinput}

Move a deprecated plan's subscriptions to another plan.

Attributes:
    to: The slug of the target plan: published, in the same product, with the same auth strategy.
    dry_run: True to report what would move without moving it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `to` | string | yes | To. |
| `dry_run` | boolean | no | Dry Run. |

### `ApiPlanMigration` {#schema-apiplanmigration}

What a migration moved (or, on a dry run, would move).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `from_plan` | `PlanRef` | yes | From Plan. |
| `to_plan` | `PlanRef` | yes | To Plan. |
| `dry_run` | boolean | yes | Dry Run. |
| `from_group` | string | yes | The gateway consumer group the consumers leave (`plan:payments-standard`). |
| `to_group` | string | yes | The gateway consumer group the consumers join. |
| `subscriptions` | integer | yes | How many subscriptions moved (or would move). |
| `credentials_changed` | boolean | no | Always false: consumers keep their keys, only their group changes. |
| `message` | string | yes | One sentence saying what happened. |

### `ApiPlanPatch` {#schema-apiplanpatch}

A partial update. Omitted fields are left alone; ``null`` clears an optional field.

``limits`` and ``environments`` are replaced as a whole. The slug is deliberately absent: it is
the handle subscriptions name.

**Lifecycle** (APX-1.4): ``state`` moves along :mod:`app.api_lifecycle`'s steps. ``retire_at``,
``deprecation_message`` and ``successor`` describe a deprecation, so they are accepted only for a
plan that is (or is becoming) ``deprecated``; reinstating it (``published``) clears them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `auth_strategy` | enum `"key_auth"`, `"oauth2_client_credentials"`, `"mtls"`, `"none"` or null | no | Auth Strategy. |
| `auth_config` | `PlanAuthConfig` or null | no | Auth Config. |
| `limits` | array of `PlanLimit` or null | no | Limits. |
| `concurrency` | integer or null | no | Concurrency. |
| `approval` | enum `"auto"`, `"manual"` or null | no | Approval. |
| `environments` | array of string or null | no | Environments. |
| `credential_ttl_days` | integer or null | no | Credential Ttl Days. |
| `terms_url` | string or null | no | Terms URL. |
| `pricing_note` | string or null | no | Pricing Note. |
| `billing_ref` | string or null | no | Billing Ref. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` or null | no | State. |
| `retire_at` | string (date-time) or null | no | Deprecated plans: the date it retires (UTC when no offset is given). |
| `deprecation_message` | string or null | no | Deprecated plans: what subscribed application owners are told. |
| `successor` | string or null | no | Deprecated plans: the slug of the published plan, same auth strategy, consumers move to. |

### `ApiPlanRecord` {#schema-apiplanrecord}

A stored plan.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `product` | string | yes | The product's slug. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `auth_strategy` | enum `"key_auth"`, `"oauth2_client_credentials"`, `"mtls"`, `"none"` | yes | Auth Strategy. |
| `auth_config` | `PlanAuthConfig` | yes | Auth Config. |
| `limits` | array of `PlanLimit` | no | Limits. |
| `concurrency` | integer or null | no | Concurrency. |
| `approval` | enum `"auto"`, `"manual"` | yes | Approval. |
| `environments` | array of `PlanEnvironment` | no | Environments. |
| `declared_only` | boolean | yes | True while no environment can be provisioned: the plan is recorded, not pushed to a gateway. |
| `credential_ttl_days` | integer or null | no | Credential Ttl Days. |
| `terms_url` | string or null | no | Terms URL. |
| `pricing_note` | string or null | no | Pricing Note. |
| `billing_ref` | string or null | no | Internal; never exported or shown on the portal. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` | yes | State. |
| `accepts_subscriptions` | boolean | no | True only for a published plan; a deprecated one blocks new subscriptions. |
| `deprecated_at` | string or null | no | Deprecated At timestamp (ISO 8601). |
| `retire_at` | string or null | no | When a deprecated plan retires. |
| `retired_at` | string or null | no | Retired At timestamp (ISO 8601). |
| `deprecation_message` | string or null | no | Deprecation Message. |
| `successor` | `PlanRef` or null | no | The plan consumers move to. |
| `owners_notified_at` | string or null | no | When subscribed application owners were told of the deprecation (once). |
| `notices` | array of `PlanNotice` | no | E.g. `api-plan-declared-only`, `api-plan-deprecated`. |
| `warnings` | array of `PlanNotice` | no | E.g. `api-plan-auth-mismatch`, one per member that does not match. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |

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
    state: ``draft`` (default) or ``published``; a product is deprecated and retired by an update
        once it exists (APX-1.4, :mod:`app.api_lifecycle`).
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

**Lifecycle** (APX-1.4): ``state`` moves along :mod:`app.api_lifecycle`'s steps; ``retire_at``
and ``deprecation_message`` describe a deprecation and are accepted only for a product that is
(or is becoming) ``deprecated``. A product retires once every plan of it is retired.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `owner_team` | string or null | no | Owner Team. |
| `visibility` | enum `"private"`, `"workspace"`, `"portal"` or null | no | Visibility. |
| `state` | enum `"draft"`, `"published"`, `"deprecated"`, `"retired"` or null | no | State. |
| `retire_at` | string (date-time) or null | no | Deprecated products: the date it retires (UTC when no offset is given). |
| `deprecation_message` | string or null | no | Deprecated products: what consumers are told. |

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
| `deprecated_at` | string or null | no | Deprecated At timestamp (ISO 8601). |
| `retire_at` | string or null | no | When a deprecated product retires. |
| `retired_at` | string or null | no | Retired At timestamp (ISO 8601). |
| `deprecation_message` | string or null | no | Deprecation Message. |
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
