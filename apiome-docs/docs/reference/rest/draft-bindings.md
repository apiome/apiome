---
title: "Draft bindings"
description: "REST endpoints tagged draft-bindings: 7 operations."
sidebar_position: 20
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `draft-bindings` · 7 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/bindings` {#list-bindings-v1-tenants-tenant-slug-projects-project-ref-bindings-get}

**List a project's branch-to-draft bindings**

A page of the project's bindings, newest first — active ones and the released rows that are their history.

Filters combine: `version` (revision id or version label) and `active` (`true` for the live bindings, `false` for released ones).

Requires `projects:view`.

Operation id: `list_bindings_v1_tenants__tenant_slug__projects__project_ref__bindings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Revision id or version label. |
| `active` | query | boolean or null | no | Active (`true`) or released (`false`) bindings only. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Bindings to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's branch-to-draft bindings. | `application/json` [`BindingListResponse`](#schema-bindinglistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/bindings/{binding_id}` {#read-binding-v1-tenants-tenant-slug-projects-project-ref-bindings-binding-id-get}

**Read one binding**

A binding with its outstanding sync candidates and the ones already settled.

Requires `projects:view`.

Operation id: `read_binding_v1_tenants__tenant_slug__projects__project_ref__bindings__binding_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `binding_id` | path | string | yes | Path parameter identifying the binding id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one binding. | `application/json` [`DraftBindingDetail`](#schema-draftbindingdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding` {#read-version-binding-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-get}

**Read a version's repository binding**

Where a version stands: its active binding with everything outstanding on it, and the bindings it has had before.

Requires `projects:view`.

Operation id: `read_version_binding_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a version's repository binding. | `application/json` [`VersionBindingStatus`](#schema-versionbindingstatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding` {#bind-version-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-post}

**Bind a draft version to a repository ref**

Make this draft the API review unit of one repository ref and source path. The ref is resolved and the selection read through a **stored** credential before anything is written — that read is the authorization check, and it is what produces the commit and the `sha256:` source digest the binding records.

Name the repository with either `repository_id` (a registered tenant repository, whose linked-account credential authorizes the read) or `repo_url` (with an optional `linked_account_id` of your own). Credentials are never accepted in the body.

A published version cannot be bound (`409 binding-version-published`), and a version has at most one active binding: pass `replace: true` to release the current one and bind anew, or the request is refused with `409 binding-already-bound`. The released row stays as history.

Requires `versions:edit`.

Operation id: `bind_version_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for bind a draft version to a repository ref.

- `application/json` — [`DraftBindingCreate`](#schema-draftbindingcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for bind a draft version to a repository ref. | `application/json` [`DraftBindingDetail`](#schema-draftbindingdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding` {#release-version-binding-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-delete}

**Release a version's repository binding**

Stop this draft being the review unit of its ref. The binding row is **kept** — stamped released, with who released it and when — and any outstanding sync candidates on it are superseded, because a released binding can never act on one.

Requires `versions:edit`.

Operation id: `release_version_binding_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for release a version's repository binding. | `application/json` [`DraftBindingRecord`](#schema-draftbindingrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/candidates/{candidate_id}` {#resolve-binding-candidate-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-candidates-candidate-id-post}

**Settle an outstanding sync candidate**

Decide what happens to an observed ref update.

`applied` records that the draft is in sync with the candidate's commit: the source is re-read at that commit — so the digest stored is one that was actually fetched — and the binding's synchronized pair advances to it, which is the base the next update is compared against. It does **not** modify the draft; three-way synchronization (GNC-2.3) settles a candidate this way after it has applied the changes.

`dismissed` leaves the binding exactly where it is.

A candidate settles once: a settled one is refused with `409 binding-candidate-resolved`.

Requires `versions:edit`.

Operation id: `resolve_binding_candidate_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_candidates__candidate_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `candidate_id` | path | string | yes | Path parameter identifying the candidate id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for settle an outstanding sync candidate.

- `application/json` — [`SyncCandidateResolve`](#schema-synccandidateresolve)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for settle an outstanding sync candidate. | `application/json` [`DraftBindingDetail`](#schema-draftbindingdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/check` {#check-version-binding-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-check-post}

**Check whether the bound ref has moved**

Ask the provider where the bound ref is now. When it has moved, a **sync candidate** is recorded — the commit and digest the binding is at, and the commit the ref moved to — and nothing about the draft changes. When it has not, the request is refused with `409 binding-unchanged`.

This is the same thing a push to the ref does through the repository webhook; it exists so a binding can be reconciled without waiting for one.

Requires `versions:edit`.

Operation id: `check_version_binding_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_check_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for check whether the bound ref has moved. | `application/json` [`DraftBindingDetail`](#schema-draftbindingdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BindingListResponse` {#schema-bindinglistresponse}

A page of a project's bindings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `bindings` | array of [`DraftBindingRecord`](#schema-draftbindingrecord) | no | Bindings, newest first. |
| `count` | integer | yes | How many bindings this page holds. |
| `total` | integer | yes | How many bindings match the filters in all. |
| `limit` | integer | yes | The page size used. |
| `offset` | integer | yes | The offset used. |

### `DraftBindingCreate` {#schema-draftbindingcreate}

Bind a draft version to a repository ref and source path.

Exactly one of ``repository_id`` and ``repo_url`` identifies the repository: a registered
tenant repository (whose stored linked-account credential authorizes the read) or a URL, for a
public repository or one the caller's own linked account can reach. A credential is never
accepted in the body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repository_id` | string or null | no | Registered tenant repository to bind to. |
| `repo_url` | string or null | no | Repository URL, when no registered repository is used. |
| `ref` | string or null | no | Branch or tag; defaults to the repository's default branch. |
| `path` | string | no | Path or glob selecting the source; empty selects the whole tree. |
| `linked_account_id` | string or null | no | The caller's own linked account whose stored token authorizes the read. |
| `replace` | boolean | no | Release the version's current binding and bind it anew. Without it a version that is already bound is refused with `binding-already-bound`. |

### `DraftBindingDetail` {#schema-draftbindingdetail}

A binding with what is outstanding on it and what has already been settled.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `binding` | [`DraftBindingRecord`](#schema-draftbindingrecord) | yes | Binding. |
| `pending` | array of `SyncCandidateRecord` | no | Outstanding sync candidates, newest first. |
| `history` | array of `SyncCandidateRecord` | no | Settled candidates, newest first — applied, dismissed, and superseded. |

### `DraftBindingRecord` {#schema-draftbindingrecord}

One stored binding — active or released.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The binding id. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `version_id` | string | yes | The bound draft version (revision). |
| `version_label` | string or null | no | The version's label, e.g. `1.2.0`. |
| `repository_id` | string or null | no | The registered tenant repository the binding was authorized through; null once that registration is removed, which leaves the binding readable but unusable. |
| `provider` | string | yes | `github`, `gitlab`, or `bitbucket`. |
| `repo_full_name` | string | yes | Lowercased `owner/name`. |
| `repo_url` | string | yes | Canonical repository URL. |
| `ref` | string | yes | Branch or tag the draft is the review unit of. |
| `path` | string | no | Path or glob selecting the source; empty is the whole tree. |
| `commit_sha` | string | yes | Commit the binding is currently synchronized with. |
| `source_digest` | string | yes | `sha256:` digest of the selected source at `commit_sha`. |
| `synchronized_at` | string (date-time) | yes | When `commit_sha` / `source_digest` last moved. |
| `browse_url` | string or null | no | Human URL for the bound source at `commit_sha`. |
| `active` | boolean | yes | True while this is the draft's binding. |
| `created_by` | string or null | no | Who bound it; null once that user is deleted. |
| `created_by_name` | string or null | no | Their display name. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) | yes | Last update timestamp (ISO 8601). |
| `released_at` | string (date-time) or null | no | When it stopped being the draft's binding; null while it is. |
| `released_by` | string or null | no | Who released it. |
| `release_reason` | enum `"replaced"`, `"unbound"`, `"repository_removed"` or null | no | `replaced`, `unbound`, or `repository_removed`. |
| `pending_candidate_count` | integer | no | Outstanding sync candidates on this binding. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SyncCandidateResolve` {#schema-synccandidateresolve}

Settle an outstanding sync candidate.

Attributes:
    status: ``applied`` — the draft is now in sync with the candidate's commit, so the
        binding's synchronized pair advances to it — or ``dismissed``, which leaves the
        binding exactly where it is.
    note: Why, kept with the settled row.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | enum `"applied"`, `"dismissed"` | yes | Status. |
| `note` | string or null | no | Note. |

### `VersionBindingStatus` {#schema-versionbindingstatus}

Where one version stands with respect to a repository.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_label` | string or null | no | Version Label. |
| `published` | boolean | yes | Published versions cannot be bound; an existing binding stays readable. |
| `bound` | boolean | yes | Whether the version has an active binding. |
| `binding` | [`DraftBindingDetail`](#schema-draftbindingdetail) or null | no | The active binding, when there is one. |
| `released` | array of [`DraftBindingRecord`](#schema-draftbindingrecord) | no | Previously active bindings, newest first. |
