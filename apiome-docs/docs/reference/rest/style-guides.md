---
title: "Style guides"
description: "REST endpoints tagged style-guides: 19 operations."
sidebar_position: 70
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `style-guides` · 19 operations

## `GET /v1/style-guides/{tenant_slug}` {#list-style-guides-v1-style-guides-tenant-slug-get}

**List Style Guides**

List the tenant's style guides with list-view rollups (rules on, assignments).

Operation id: `list_style_guides_v1_style_guides__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list style guides. | `application/json` [`StyleGuideListResponse`](#schema-styleguidelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/style-guides/{tenant_slug}` {#create-style-guide-v1-style-guides-tenant-slug-post}

**Create Style Guide**

Create a custom guide; ``sourceGuideId`` copies that guide's rules (duplicate).

Operation id: `create_style_guide_v1_style_guides__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create style guide.

- `application/json` — [`StyleGuideCreateRequest`](#schema-styleguidecreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create style guide. | `application/json` [`StyleGuideOut`](#schema-styleguideout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/style-guides/{tenant_slug}/assignments/projects/{project_id}` {#unassign-project-v1-style-guides-tenant-slug-assignments-projects-project-id-delete}

**Unassign Project**

Remove a project's guide assignment; it falls back to the tenant default.

Operation id: `unassign_project_v1_style_guides__tenant_slug__assignments_projects__project_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unassign project. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/style-guides/{tenant_slug}/{guide_id}` {#update-style-guide-v1-style-guides-tenant-slug-guide-id-patch}

**Update Style Guide**

Rename / re-describe a custom guide (the builtin guide is read-only).

Operation id: `update_style_guide_v1_style_guides__tenant_slug___guide_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update style guide.

- `application/json` — [`StyleGuideUpdateRequest`](#schema-styleguideupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update style guide. | `application/json` [`StyleGuideOut`](#schema-styleguideout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/style-guides/{tenant_slug}/{guide_id}` {#delete-style-guide-v1-style-guides-tenant-slug-guide-id-delete}

**Delete Style Guide**

Delete a custom guide; its assignments cascade and the affected projects fall back
to the tenant default. Deleting the current default promotes the builtin guide.

Operation id: `delete_style_guide_v1_style_guides__tenant_slug___guide_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete style guide. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/style-guides/{tenant_slug}/{guide_id}/assignments/projects/{project_id}` {#assign-project-v1-style-guides-tenant-slug-guide-id-assignments-projects-project-id-put}

**Assign Project**

Assign a guide to one project (replaces the project's previous assignment).

A project-level assignment wins over the tenant default in the GOV-1.4 resolution
order, so the project's next lint run scores under this guide.

Operation id: `assign_project_v1_style_guides__tenant_slug___guide_id__assignments_projects__project_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign project. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/custom-rules` {#get-style-guide-custom-rules-v1-style-guides-tenant-slug-guide-id-custom-rules-get}

**Get Style Guide Custom Rules**

The guide's custom-rules YAML document (GOV-2.3, #4435).

Returns the Spectral-compatible YAML the custom-rules tab edits. Readable by any tenant
member — the tab renders read-only for non-admins and the built-in guide.

Operation id: `get_style_guide_custom_rules_v1_style_guides__tenant_slug___guide_id__custom_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get style guide custom rules. | `application/json` [`StyleGuideCustomRulesResponse`](#schema-styleguidecustomrulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/style-guides/{tenant_slug}/{guide_id}/custom-rules` {#put-style-guide-custom-rules-v1-style-guides-tenant-slug-guide-id-custom-rules-put}

**Put Style Guide Custom Rules**

Replace the guide's custom-rule rows from YAML (GOV-2.3, #4435).

Strictly validates the document (same contract as ``POST /v1/lint/custom-rules/validate``,
but ``rules: {}`` clears every custom rule). Built-in rows are untouched. Malformed YAML
returns HTTP 422 with a pointer for inline editor markers.

Operation id: `put_style_guide_custom_rules_v1_style_guides__tenant_slug___guide_id__custom_rules_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put style guide custom rules.

- `application/json` — [`StyleGuideCustomRulesPutRequest`](#schema-styleguidecustomrulesputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put style guide custom rules. | `application/json` [`StyleGuideCustomRulesResponse`](#schema-styleguidecustomrulesresponse) |
| 422 | Malformed guide: `detail.message` explains the problem and `detail.pointer` points at the offending YAML node. | — |

## `POST /v1/style-guides/{tenant_slug}/{guide_id}/custom-rules/preview` {#preview-style-guide-custom-rules-v1-style-guides-tenant-slug-guide-id-custom-rules-preview-post}

**Preview Style Guide Custom Rules**

Dry-run draft custom rules against a project revision (GOV-2.3, #4435).

Parses the draft YAML, reconstructs the revision's OpenAPI document, evaluates only the
custom rules, and returns their violations — nothing is persisted.

Operation id: `preview_style_guide_custom_rules_v1_style_guides__tenant_slug___guide_id__custom_rules_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview style guide custom rules.

- `application/json` — [`StyleGuideCustomRulesPreviewRequest`](#schema-styleguidecustomrulespreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview style guide custom rules. | `application/json` [`StyleGuideCustomRulesPreviewResponse`](#schema-styleguidecustomrulespreviewresponse) |
| 422 | Malformed draft YAML: `detail.message` + `detail.pointer`. | — |

## `PUT /v1/style-guides/{tenant_slug}/{guide_id}/default` {#set-tenant-default-v1-style-guides-tenant-slug-guide-id-default-put}

**Set Tenant Default**

Make a guide the tenant default — what every project without its own assignment
lints under from the next run onward.

Operation id: `set_tenant_default_v1_style_guides__tenant_slug___guide_id__default_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set tenant default. | `application/json` [`StyleGuideOut`](#schema-styleguideout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/policy` {#get-style-guide-policy-settings-v1-style-guides-tenant-slug-guide-id-policy-get}

**Get Style Guide Policy Settings**

Return draft policy gate settings for a style guide (CLX-1.3, #4850).

Operation id: `get_style_guide_policy_settings_v1_style_guides__tenant_slug___guide_id__policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get style guide policy settings. | `application/json` [`StyleGuidePolicySettingsOut`](#schema-styleguidepolicysettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/style-guides/{tenant_slug}/{guide_id}/policy` {#put-style-guide-policy-settings-v1-style-guides-tenant-slug-guide-id-policy-put}

**Put Style Guide Policy Settings**

Update draft policy gates and optionally snapshot a policy pack (CLX-1.3, #4850).

Also carries the CTG-3.4 (#4478) breaking-publish guardrail level and the COL-2.3
(#4519) approval policy, both of which the publish flow reads through the same
guide-resolution chain.

``requiredReviewerRole`` distinguishes *omitted* from *null*: omitting it leaves the
stored role alone, sending ``null`` clears it. Every other field keeps the
omit-to-leave-unchanged rule the endpoint has always had.

Operation id: `put_style_guide_policy_settings_v1_style_guides__tenant_slug___guide_id__policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put style guide policy settings.

- `application/json` — [`StyleGuidePolicySettingsPutRequest`](#schema-styleguidepolicysettingsputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put style guide policy settings. | `application/json` [`StyleGuidePolicySettingsOut`](#schema-styleguidepolicysettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/policy-versions` {#list-style-guide-policy-versions-v1-style-guides-tenant-slug-guide-id-policy-versions-get}

**List Style Guide Policy Versions**

List immutable policy pack versions for a style guide (CLX-1.3, #4850).

Operation id: `list_style_guide_policy_versions_v1_style_guides__tenant_slug___guide_id__policy_versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list style guide policy versions. | `application/json` [`StyleGuidePolicyVersionListResponse`](#schema-styleguidepolicyversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/style-guides/{tenant_slug}/{guide_id}/policy-versions` {#publish-style-guide-policy-version-v1-style-guides-tenant-slug-guide-id-policy-versions-post}

**Publish Style Guide Policy Version**

Snapshot the live guide into a new immutable policy pack (CLX-1.3, #4850).

Operation id: `publish_style_guide_policy_version_v1_style_guides__tenant_slug___guide_id__policy_versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for publish style guide policy version. | `application/json` [`StyleGuidePolicyVersionOut`](#schema-styleguidepolicyversionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/policy-versions/{policy_version_id}` {#get-style-guide-policy-version-v1-style-guides-tenant-slug-guide-id-policy-versions-policy-version-id-get}

**Get Style Guide Policy Version**

Fetch one policy pack version for a style guide (CLX-1.3, #4850).

Operation id: `get_style_guide_policy_version_v1_style_guides__tenant_slug___guide_id__policy_versions__policy_version_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `policy_version_id` | path | string | yes | Path parameter identifying the policy version id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get style guide policy version. | `application/json` [`StyleGuidePolicyVersionOut`](#schema-styleguidepolicyversionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/revisions` {#list-style-guide-revisions-v1-style-guides-tenant-slug-guide-id-revisions-get}

**List Style Guide Revisions**

The guide's immutable revision history, newest first (GOV-1.6, #4432).

One entry per edit — create, rename, rule-catalog save, custom-rule save, policy-gate
change — with the change kind, the actor, and the fingerprints a lint result pins to.
Saves that changed nothing are not entries: the history is real changes only.

Reading self-heals a guide with no history yet (created before GOV-1.6, or seeded by the
V159 migration): its current state is captured as revision 1 rather than showing an empty
list for a guide that demonstrably exists. Readable by any tenant member — compliance
review is not an admin-only activity.

Operation id: `list_style_guide_revisions_v1_style_guides__tenant_slug___guide_id__revisions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list style guide revisions. | `application/json` [`StyleGuideRevisionListResponse`](#schema-styleguiderevisionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/revisions/{revision_id}` {#get-style-guide-revision-v1-style-guides-tenant-slug-guide-id-revisions-revision-id-get}

**Get Style Guide Revision**

One immutable revision with the rules and policy gates it froze (GOV-1.6, #4432).

This is what makes a past lint result defendable: a report carries ``guideRevisionId``, and
this endpoint returns exactly the ruleset that produced it — including custom rule
definitions — no matter how the live guide has changed since.

Operation id: `get_style_guide_revision_v1_style_guides__tenant_slug___guide_id__revisions__revision_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get style guide revision. | `application/json` [`StyleGuideRevisionDetailOut`](#schema-styleguiderevisiondetailout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/style-guides/{tenant_slug}/{guide_id}/rules` {#get-style-guide-rules-v1-style-guides-tenant-slug-guide-id-rules-get}

**Get Style Guide Rules**

The guide's built-in rule catalog view (GOV-2.2, #4434).

Every GOV-1.2 registry rule with its category, default severity and rationale, merged
with this guide's ``style_guide_rules`` state (enabled + severity override). Readable by
any tenant member — the rule catalog tab renders read-only for non-admins.

Operation id: `get_style_guide_rules_v1_style_guides__tenant_slug___guide_id__rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get style guide rules. | `application/json` [`StyleGuideRulesResponse`](#schema-styleguiderulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/style-guides/{tenant_slug}/{guide_id}/rules` {#put-style-guide-rules-v1-style-guides-tenant-slug-guide-id-rules-put}

**Put Style Guide Rules**

Replace the guide's built-in rule rows (GOV-2.2, #4434) — the catalog tab's save.

The body is the guide's complete desired built-in rule state (at most one entry per
registered rule id; unknown ids are rejected). Custom-rule rows are untouched. The next
lint run under the guide picks the new rows up via GOV-1.4's content-addressed compile.

Operation id: `put_style_guide_rules_v1_style_guides__tenant_slug___guide_id__rules_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `guide_id` | path | string | yes | Style guide identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put style guide rules.

- `application/json` — [`StyleGuideRulesPutRequest`](#schema-styleguiderulesputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put style guide rules. | `application/json` [`StyleGuideRulesResponse`](#schema-styleguiderulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `StyleGuideCreateRequest` {#schema-styleguidecreaterequest}

Create a custom style guide, optionally copying an existing guide's rules (GOV-2.1).

``source_guide_id`` implements both duplicate flows: duplicating a custom guide and
"start from Recommended" (duplicating the read-only builtin guide as an editable copy).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Guide display name (unique per tenant). |
| `description` | string or null | no | Optional free-text description. |
| `sourceGuideId` | string or null | no | Guide (same tenant) whose rule rows are copied into the new guide. |
| `externalLintProfile` | string or null | no | CLX-2.2 profile: baseline \| tenant_guide \| strict (default baseline). |

### `StyleGuideCustomRulesPreviewRequest` {#schema-styleguidecustomrulespreviewrequest}

Dry-run custom-rule evaluation against a project revision (GOV-2.3, #4435).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `yaml` | string | yes | Draft custom-rules YAML to evaluate (not persisted). |
| `projectId` | string | yes | The project owning the revision to lint against. |
| `versionRecordId` | string | yes | The revision (``versions.id``) to lint against. |

### `StyleGuideCustomRulesPreviewResponse` {#schema-styleguidecustomrulespreviewresponse}

Live violations from evaluating draft custom rules (GOV-2.3, #4435).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `versionRecordId` | string | yes | Version Record ID. |
| `versionId` | string | yes | Version ID. |
| `count` | integer | yes | Number of violations returned. |
| `findings` | array of `LintFindingOut` | yes | Custom-rule violations, sorted deterministically. |
| `ruleErrors` | map of string | no | Rule id -&gt; sandbox abort reason for rules that could not be evaluated. |

### `StyleGuideCustomRulesPutRequest` {#schema-styleguidecustomrulesputrequest}

Replace a guide's custom-rule rows from YAML (GOV-2.3, #4435).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `yaml` | string | yes | The style-guide YAML document (`rules.<id>: {description, severity, given, then}`). |

### `StyleGuideCustomRulesResponse` {#schema-styleguidecustomrulesresponse}

A guide's custom-rules YAML document (GOV-2.3, #4435).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guideId` | string | yes | The guide's id. |
| `guideName` | string | yes | The guide's display name. |
| `source` | string | yes | builtin (read-only, seeded) \| custom (tenant-authored). |
| `yaml` | string | yes | The Spectral-compatible custom-rules YAML document. |
| `ruleCount` | integer | yes | Number of custom rules in the document (0 for ``rules: {}``). |

### `StyleGuideListResponse` {#schema-styleguidelistresponse}

The tenant's style guides for the Control Panel list view (GOV-2.1, #4433).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guides` | array of [`StyleGuideOut`](#schema-styleguideout) | yes | Every guide of the tenant, builtin first then by name. |
| `count` | integer | yes | Number of guides (== len(guides)). |

### `StyleGuideOut` {#schema-styleguideout}

One tenant style guide with its list-view rollups (GOV-2.1, #4433).

``source == 'builtin'`` marks the seeded read-only "Apiome Recommended" guide: it can be
duplicated and assigned but never edited or deleted. ``is_default`` is the tenant-default
badge; ``tenant_assigned`` reports an explicit tenant-wide assignment row (which resolves
ahead of the default flag in the GOV-1.4 chain — the API keeps the two in sync).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `source` | string | yes | builtin (read-only, seeded) \| custom (tenant-authored). |
| `isDefault` | boolean | yes | True for the tenant's default guide (the list view's default badge). |
| `ruleCount` | integer | yes | Total style_guide_rules rows on the guide (enabled and disabled). |
| `enabledRuleCount` | integer | yes | Rules currently enabled — the list view's 'rules on' column. |
| `tenantAssigned` | boolean | yes | True when an explicit tenant-wide assignment row points at this guide. |
| `projectAssignments` | array of `StyleGuideProjectAssignmentOut` | no | Projects explicitly assigned to this guide, sorted by project name. |
| `externalLintProfile` | string | no | CLX-2.2 OpenAPI external validation pack profile: baseline \| tenant_guide \| strict. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `StyleGuidePolicySettingsOut` {#schema-styleguidepolicysettingsout}

Draft policy gate settings on a live style guide (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guideId` | string | yes | Guide ID. |
| `axisGates` | object | no | Per-axis min grade/score floors, e.g. {quality: {minGrade: B}}. |
| `requiredCoverage` | array of string | no | Required Coverage. |
| `ciOutcomes` | `StyleGuideCiOutcomesOut` | no | Ci Outcomes. |
| `breakingPublishPolicy` | enum `"off"`, `"warn"`, `"block"` | no | Guardrail applied when a publish is breaking without a semver major bump (CTG-3.4): off, warn (default), or block. |
| `requiredApprovals` | integer | no | Review approvals a draft must carry before it can be published (COL-2.3); 0 (default) disables the approval gate. |
| `requiredReviewerRole` | string or null | no | Role slug at least one of those approvals must come from (COL-2.3); null means any approver counts. |

### `StyleGuidePolicySettingsPutRequest` {#schema-styleguidepolicysettingsputrequest}

Replace draft policy gate settings on a custom style guide (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `axisGates` | object or null | no | Axis Gates. |
| `requiredCoverage` | array of string or null | no | Required Coverage. |
| `ciOutcomes` | `StyleGuideCiOutcomesOut` or null | no | Ci Outcomes. |
| `breakingPublishPolicy` | enum `"off"`, `"warn"`, `"block"` or null | no | Breaking-publish guardrail level (CTG-3.4); omit to leave unchanged. |
| `requiredApprovals` | integer or null | no | Approvals required before publish (COL-2.3); 0 disables the gate, omit to leave unchanged. |
| `requiredReviewerRole` | string or null | no | Role slug at least one approval must come from (COL-2.3); send null to clear it, omit to leave unchanged. |
| `snapshot` | boolean | no | When true (default), also append an immutable policy pack version. |

### `StyleGuidePolicyVersionListResponse` {#schema-styleguidepolicyversionlistresponse}

List of policy pack versions for a style guide (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`StyleGuidePolicyVersionOut`](#schema-styleguidepolicyversionout) | no | Versions. |
| `count` | integer | no | Number of count. |

### `StyleGuidePolicyVersionOut` {#schema-styleguidepolicyversionout}

One immutable style-guide policy pack version (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `guideId` | string | yes | Guide ID. |
| `versionNumber` | integer | yes | Version Number. |
| `contentFingerprint` | string | yes | Content Fingerprint. |
| `axisGates` | object | no | Axis Gates. |
| `requiredCoverage` | array of string | no | Required Coverage. |
| `ciOutcomes` | `StyleGuideCiOutcomesOut` | no | Ci Outcomes. |
| `actorUserId` | string or null | no | Actor User ID. |
| `actorLabel` | string or null | no | Actor Label. |
| `createdAt` | string or null | no | Created At. |

### `StyleGuideRevisionDetailOut` {#schema-styleguiderevisiondetailout}

A style-guide revision including its frozen rules and policy gates (GOV-1.6, #4432).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Revision id — what a lint result pins to. |
| `guideId` | string | yes | The guide this revision belongs to. |
| `revisionNumber` | integer | yes | Monotonic revision number within the guide (starts at 1). |
| `changeKind` | string | yes | What produced the revision: created \| edited \| rules_changed \| custom_rules_changed \| policy_changed \| imported. |
| `name` | string | yes | Guide name at the time of this revision. |
| `description` | string or null | no | Guide description at the time of this revision. |
| `externalLintProfile` | string or null | no | External validation profile at the time of this revision (CLX-2.2). |
| `ruleCount` | integer | no | Number of rule rows frozen into this revision. |
| `enabledRuleCount` | integer | no | How many of those rules were enabled. |
| `customRuleCount` | integer | no | How many of those rules carried a custom definition (GOV-1.3). |
| `contentFingerprint` | string | yes | SHA-256 of the frozen rule rows — identical to the fingerprint the linter stamps on the compiled guide, which is how lint results resolve their revision. |
| `snapshotFingerprint` | string | yes | SHA-256 of the whole snapshot (identity + rules + policy gates). Equal fingerprints mean an edit changed nothing, and no revision is appended. |
| `actorUserId` | string or null | no | User who made the change; null for system captures or deleted users. |
| `actorLabel` | string or null | no | Human-readable actor label recorded at the time of the change. |
| `createdAt` | string or null | no | When the revision was recorded (rows are write-once). |
| `rules` | array of object | no | The guide's rule rows as they were, sorted by rule id: `ruleId`-equivalent `rule_id`, `enabled`, `severity`, and `custom_def` for custom rules. |
| `policy` | object | no | Draft policy gates at the time of this revision: `axisGates`, `requiredCoverage`, `ciOutcomes` (CLX-1.3). |

### `StyleGuideRevisionListResponse` {#schema-styleguiderevisionlistresponse}

A style guide's immutable revision history, newest first (GOV-1.6, #4432).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guideId` | string | yes | Guide ID. |
| `guideName` | string | yes | Guide Name. |
| `revisions` | array of `StyleGuideRevisionOut` | no | Revisions. |
| `count` | integer | no | Number of count. |

### `StyleGuideRulesPutRequest` {#schema-styleguiderulesputrequest}

Replace a guide's built-in rule rows (GOV-2.2, #4434).

The request is the guide's complete desired built-in rule state: rows for registry rules
omitted here are deleted (leaving those rules disabled at their defaults). Custom-rule
rows (``custom_def`` present) are untouched — they are managed by the custom-rules tab.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rules` | array of `StyleGuideRuleOverrideIn` | yes | The guide's built-in rule rows; at most one entry per rule id. |

### `StyleGuideRulesResponse` {#schema-styleguiderulesresponse}

A guide's full built-in rule catalog view (GOV-2.2, #4434), sorted by rule id.

Merges the GOV-1.2 registry with the guide's ``style_guide_rules`` overrides so the rule
catalog tab renders and saves from one payload. Custom rules (GOV-1.3 rows carrying a
``custom_def``) are not part of this view.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guideId` | string | yes | The guide's id. |
| `guideName` | string | yes | The guide's display name. |
| `source` | string | yes | builtin (read-only, seeded) \| custom (tenant-authored). |
| `rules` | array of `StyleGuideRuleOut` | yes | Every registered built-in rule with this guide's state, sorted by ruleId. |
| `count` | integer | yes | Number of registry rules (== len(rules)). |
| `enabledCount` | integer | yes | Rules this guide currently enables. |
| `docsPage` | string | yes | Repository-relative path of the rule reference page docsAnchor points into. |

### `StyleGuideUpdateRequest` {#schema-styleguideupdaterequest}

Rename / re-describe a custom style guide (GOV-2.1). Builtin guides are read-only.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | New display name, when renaming. |
| `description` | string or null | no | New description; empty string clears it. |
| `externalLintProfile` | string or null | no | CLX-2.2 profile: baseline \| tenant_guide \| strict. |
