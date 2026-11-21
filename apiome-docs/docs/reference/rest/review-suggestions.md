---
title: "Review suggestions"
description: "REST endpoints tagged review-suggestions: 4 operations."
sidebar_position: 85
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.618.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `review-suggestions` · 4 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions` {#list-suggestions-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-suggestions-get}

**List a review's suggested changes**

Every suggestion on the review, oldest first. Requires `projects:view`.

Operation id: `list_suggestions_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__suggestions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a review's suggested changes. | `application/json` [`ReviewSuggestionListResponse`](#schema-reviewsuggestionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions` {#create-suggestion-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-suggestions-post}

**Suggest a change**

Propose an RFC 6902 patch to one class or property of the reviewed version.

Open to the review's current-round reviewers, its requester, and project editors.

Operation id: `create_suggestion_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__suggestions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for suggest a change.

- `application/json` — [`SuggestionCreate`](#schema-suggestioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for suggest a change. | `application/json` [`SuggestionRecord`](#schema-suggestionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions/{suggestion_id}/apply` {#apply-suggestion-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-suggestions-suggestion-id-apply-post}

**Apply a suggested change**

Merge the suggestion onto the element and write it.

`409 suggestion-stale` (with `conflict_paths`) when the element changed since in a way that
overlaps the suggestion; it is then recorded stale and nothing else is written. The review's
requester or a project editor only, never the suggestion's author.

Operation id: `apply_suggestion_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__suggestions__suggestion_id__apply_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `suggestion_id` | path | string | yes | Path parameter identifying the suggestion id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for apply a suggested change. | `application/json` [`SuggestionApplyResult`](#schema-suggestionapplyresult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions/{suggestion_id}/reject` {#reject-suggestion-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-suggestions-suggestion-id-reject-post}

**Reject a suggested change**

Record a rejection (or its author's withdrawal), with an optional reason.

Operation id: `reject_suggestion_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__suggestions__suggestion_id__reject_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `suggestion_id` | path | string | yes | Path parameter identifying the suggestion id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for reject a suggested change.

- `application/json` — [`SuggestionDecision`](#schema-suggestiondecision)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for reject a suggested change. | `application/json` [`SuggestionRecord`](#schema-suggestionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ReviewSuggestionListResponse` {#schema-reviewsuggestionlistresponse}

A review's suggestions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `suggestions` | array of [`SuggestionRecord`](#schema-suggestionrecord) | no | Oldest first. |
| `can_decide` | boolean | yes | Whether the caller may apply or reject (others') suggestions. |

### `SuggestionApplyResult` {#schema-suggestionapplyresult}

The outcome of applying a suggestion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `suggestion` | [`SuggestionRecord`](#schema-suggestionrecord) | yes | Suggestion. |
| `element` | object | yes | The element as written. |
| `merged_around` | boolean | yes | True when the element had other edits since the suggestion, which were kept. |

### `SuggestionCreate` {#schema-suggestioncreate}

A reviewer's proposed edit.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_type` | enum `"class"`, `"property"` | yes | `class` or `property`. |
| `target_id` | string | yes | The class or class-property id, in the reviewed version. |
| `patch` | array of object | yes | RFC 6902 operations (`add`, `remove`, `replace`, `test`) over the element's canonical JSON — `{description, schema}` for a class, `{description, data}` for a property. |
| `note` | string or null | no | Why. |

### `SuggestionDecision` {#schema-suggestiondecision}

An optional reason recorded with a rejection.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reason` | string or null | no | Reason. |

### `SuggestionRecord` {#schema-suggestionrecord}

One stored suggestion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `review_id` | string | yes | Review ID. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `author_id` | string or null | no | Who proposed it. |
| `author_name` | string or null | no | Author Name. |
| `target_type` | enum `"class"`, `"property"` | yes | Target Type. |
| `target_id` | string | yes | Target ID. |
| `target_label` | string | yes | `Pet` for a class, `Pet.name` for a property. |
| `note` | string or null | no | Note. |
| `base` | object | yes | The element when the suggestion was made. |
| `patch` | array of object | yes | Patch. |
| `proposed` | object | yes | `base` with `patch` applied — what the author sees as the diff. |
| `status` | enum `"open"`, `"applied"`, `"rejected"`, `"stale"` | yes | Status. |
| `conflict_paths` | array of string | no | Why it went stale. |
| `stale` | boolean | no | For an open suggestion: true when the element changed since it was made in a way that overlaps it, so applying would conflict. Always false once decided. |
| `decided_by` | string or null | no | Decided By. |
| `decided_by_name` | string or null | no | Decided By Name. |
| `decided_at` | string (date-time) or null | no | Decided At timestamp (ISO 8601). |
| `reason` | string or null | no | Reason. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
