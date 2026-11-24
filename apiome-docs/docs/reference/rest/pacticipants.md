---
title: "Pacticipants"
description: "REST endpoints tagged pacticipants: 10 operations."
sidebar_position: 70
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.659.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pacticipants` · 10 operations

## `GET /v1/tenants/{tenant_slug}/pacticipants` {#list-tenant-pacticipants-v1-tenants-tenant-slug-pacticipants-get}

**List pacticipants**

The applications registered as pacticipants in this workspace, ordered by handle.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_tenant_pacticipants_v1_tenants__tenant_slug__pacticipants_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list pacticipants. | `application/json` [`PacticipantListResponse`](#schema-pacticipantlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pacticipants` {#register-pacticipant-v1-tenants-tenant-slug-pacticipants-post}

**Register a pacticipant**

Register an application that takes part in pacts. The handle (`slug`) is what URLs and CI name; it is derived from `name` when omitted (`Billing Service` becomes `billing-service`), is unique in the workspace, and is **not** editable afterwards.

`project` binds a provider to the project that describes it; `consumer_id` binds a consumer to its row in the consumer registry. Both are optional and must belong to this workspace. Deleting the project or the consumer clears the binding and keeps the pacticipant.

Requires `pacts:create`.

Operation id: `register_pacticipant_v1_tenants__tenant_slug__pacticipants_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a pacticipant.

- `application/json` — [`PacticipantInput`](#schema-pacticipantinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 409 | `pacticipant-slug-taken`: the workspace already has that handle. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#read-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-get}

**Read one pacticipant**

Read a pacticipant by its handle, its id, or its display name (`Billing Service` finds `billing-service`).

Requires `pacts:view`.

Operation id: `read_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#patch-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-patch}

**Update a pacticipant**

Change the display name, repository URL, main branch or bindings. A field that is left out is not changed; `null` clears `repository_url` and `main_branch` and unbinds `project` and `consumer_id`. The handle cannot be changed.

Requires `pacts:edit`.

Operation id: `patch_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update a pacticipant.

- `application/json` — [`PacticipantPatch`](#schema-pacticipantpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update a pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#remove-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-delete}

**Delete a pacticipant**

Delete a pacticipant **with all of its versions, branches and tags**. This cannot be undone. The project and the consumer it was bound to are not touched.

Requires `pacts:delete` (the built-in Owner and Admin roles).

Operation id: `remove_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a pacticipant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/branches` {#list-pacticipant-branches-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-branches-get}

**List a pacticipant's branches**

The branches versions were recorded on, by name, each with its head: the latest version recorded on it. `is_main` marks the pacticipant's main branch.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_pacticipant_branches_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__branches_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a pacticipant's branches. | `application/json` [`PacticipantBranchListResponse`](#schema-pacticipantbranchlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions` {#list-pacticipant-versions-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-get}

**List a pacticipant's versions**

The versions recorded for this pacticipant, latest recorded first, each with the branches it was recorded on and its tags. `branch` and `tag` narrow the list, so the first row of `?branch=main` is the head of `main` and the first row of `?tag=prod` is the latest version tagged `prod`.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_pacticipant_versions_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `branch` | query | string or null | no | Only versions recorded on this branch. |
| `tag` | query | string or null | no | Only versions carrying this tag. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a pacticipant's versions. | `application/json` [`PacticipantVersionListResponse`](#schema-pacticipantversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}` {#read-pacticipant-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-get}

**Read one version**

Read a version by its number, with the branches it was recorded on and its tags.

Requires `pacts:view`.

Operation id: `read_pacticipant_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one version. | `application/json` [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}` {#put-pacticipant-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-put}

**Record a version**

Record that a build produced version `number` of this pacticipant, optionally with the branch it was built from and tags. Safe to repeat:

- **A version is created once and never changes.** The first request answers `201` and stores `build_url`. A later request for the same number answers `200` with the stored version; its `build_url` is not replaced.
- **A branch head only moves forward.** The version is added to `branch`, and becomes its head only when it was recorded later than the current head (`head_moved`). Recording an older version on a branch does not move the head back.
- **Tags are added once.** Sending a tag the version already has changes nothing.

The version number is stored exactly as sent. It cannot contain a `/` here, because it is a path segment.

Requires `pacts:create`.

Operation id: `put_pacticipant_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for record a version.

- `application/json` — [`PacticipantVersionInput`](#schema-pacticipantversioninput) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a version. | `application/json` [`RecordedPacticipantVersion`](#schema-recordedpacticipantversion) |
| 201 | The version was created by this request. | `application/json` [`RecordedPacticipantVersion`](#schema-recordedpacticipantversion) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}/tags/{tag}` {#put-pacticipant-version-tag-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-tags-tag-put}

**Tag a version**

Put a tag on a recorded version. Tagging a version that already has the tag changes nothing and answers the same way. A tag may contain `/` (`feat/new-invoice`).

Requires `pacts:create`.

Operation id: `put_pacticipant_version_tag_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__tags__tag__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `tag` | path | string | yes | Path parameter identifying the tag segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for tag a version. | `application/json` [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PacticipantBranchListResponse` {#schema-pacticipantbranchlistresponse}

One page of a pacticipant's branches.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `branches` | array of `PacticipantBranchRecord` | no | By name. |
| `count` | integer | yes | How many branches were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantInput` {#schema-pacticipantinput}

A new pacticipant.

Attributes:
    name: Display name, as a Pact file or a person writes it.
    slug: The handle; derived from ``name`` when omitted, and never editable.
    repository_url: http(s) URL of the application's source repository.
    main_branch: The branch read by default when a query names none.
    project: Slug or id of the Apiome project that describes this provider.
    consumer_id: Id of this application's row in the consumer registry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Display name, as a Pact file or a person writes it. |
| `slug` | string or null | no | The handle URLs and CI name. Derived from `name` when omitted; not editable afterwards. |
| `repository_url` | string or null | no | http(s) URL of the application's source repository. |
| `main_branch` | string or null | no | The branch read by default when a query names none. |
| `project` | string or null | no | Slug or id of the project that describes this application as a provider. |
| `consumer_id` | string or null | no | Id of this application's consumer in the consumer registry. |

### `PacticipantListResponse` {#schema-pacticipantlistresponse}

One page of the tenant's pacticipants.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pacticipants` | array of [`PacticipantRecord`](#schema-pacticipantrecord) | no | By handle. |
| `count` | integer | yes | How many pacticipants were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantPatch` {#schema-pacticipantpatch}

A partial update of a pacticipant. An omitted field is left alone; ``null`` clears it.

Attributes:
    name: New display name (cannot be cleared).
    repository_url: New repository URL, or ``null`` to clear it.
    main_branch: New main branch, or ``null`` to clear it.
    project: Slug or id of the project to bind, or ``null`` to unbind.
    consumer_id: Id of the consumer to bind, or ``null`` to unbind.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | New display name. |
| `repository_url` | string or null | no | New repository URL; `null` clears it. |
| `main_branch` | string or null | no | New main branch; `null` clears it. |
| `project` | string or null | no | Project slug or id to bind; `null` unbinds. |
| `consumer_id` | string or null | no | Consumer id to bind; `null` unbinds. |

### `PacticipantRecord` {#schema-pacticipantrecord}

A stored pacticipant.

Attributes:
    id: Row id.
    tenant_id: Owning tenant.
    slug: Stable handle.
    name: Display name.
    repository_url: Source repository URL.
    main_branch: The branch read by default.
    project_id: Bound project, when this is a provider described in Apiome.
    consumer_id: Bound consumer-registry row, when this is a registered consumer.
    created_at: When it was registered.
    updated_at: When it was last changed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `repository_url` | string or null | no | Repository URL. |
| `main_branch` | string or null | no | Main Branch. |
| `project_id` | string or null | no | Project identifier the resource belongs to. |
| `consumer_id` | string or null | no | Consumer ID. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |

### `PacticipantVersionInput` {#schema-pacticipantversioninput}

What a build reports when it records a version.

Attributes:
    build_url: http(s) URL of the CI build. Kept only when this request creates the version.
    branch: The repository branch the version was built from.
    tags: Tags to put on the version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `build_url` | string or null | no | http(s) URL of the CI build. Stored only when this request creates the version. |
| `branch` | string or null | no | The repository branch this version was built from. |
| `tags` | array of string | no | Tags to put on the version (at most 50). |

### `PacticipantVersionListResponse` {#schema-pacticipantversionlistresponse}

One page of a pacticipant's versions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) | no | Latest recorded first. |
| `count` | integer | yes | How many versions were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantVersionRecord` {#schema-pacticipantversionrecord}

A stored pacticipant version.

Attributes:
    id: Row id.
    pacticipant_id: Owning pacticipant.
    number: The version string, as the build reported it.
    seq: Order of recording; a higher value was recorded later.
    build_url: The CI build that produced it.
    branches: Branches it was recorded on, by name.
    tags: Its tags, by name.
    created_by: The user who recorded it, when still known.
    actor_label: Who recorded it, as text.
    created_at: When it was recorded.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `pacticipant_id` | string | yes | Pacticipant ID. |
| `number` | string | yes | Number. |
| `seq` | integer | yes | Order of recording; a higher value was recorded later. |
| `build_url` | string or null | no | Build URL. |
| `branches` | array of string | no | Branches. |
| `tags` | array of string | no | Associated tag labels. |
| `created_by` | string or null | no | Created By. |
| `actor_label` | string or null | no | Actor Label. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |

### `RecordedPacticipantVersion` {#schema-recordedpacticipantversion}

The outcome of recording a version.

Attributes:
    version: The version as stored, with every branch and tag it now has.
    created: Whether this request created the version (false: it already existed, unchanged).
    head_moved: Whether the named branch's head moved to this version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) | yes | Version. |
| `created` | boolean | yes | False when the version already existed; it is returned unchanged. |
| `head_moved` | boolean | no | Whether the branch named in the request now has this version as its head. |
