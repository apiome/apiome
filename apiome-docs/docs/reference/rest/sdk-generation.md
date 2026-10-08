---
title: "SDK generation"
description: "REST endpoints tagged sdk-generation: 3 operations."
sidebar_position: 57
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sdk-generation` · 3 operations

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-settings` {#get-project-sdk-settings-v1-projects-tenant-slug-project-ref-sdk-settings-get}

**Get the generation settings in force for a project**

The package naming, licence header and user-agent this project's generated artifacts carry, and where they came from: `project` (an override saved here), `tenant` (the workspace default), `merged` (both), or `default` (nothing saved anywhere).

`resolved` carries the same settings with their tokens substituted for this project — the package names a publisher would actually use.

Settings are merged **key by key**, tenant first: a project that overrides only its user-agent still inherits its tenant's package patterns. `packageNamePatterns` merges one ecosystem at a time.

A key **absent** from a body inherits the next scope up; a key present as **`null`** is deliberately none, and blocks that inheritance.

Patterns may contain the tokens `{tenant}`, `{project}`, `{version}`, `{year}`, substituted from the scope being resolved. A package pattern is validated by resolving it against probe values and checking the result against its registry's naming rules, so `@acme/{project}-sdk` is accepted and `@ACME/{project}` is not.

Ecosystems: `npm`, `pypi`, `gomod`. `licenseHeader` is capped at 4,000 characters; `userAgent` at 200 and to characters legal in an HTTP header.

`publicSdkEnabled` (boolean, default `false`) is the SDK-3.3 gate: it opens the public browse portal's **Get SDK** client-kit download and its anonymous per-operation snippets for the project. It is the one setting that is an access control rather than branding, so an unset value means *not allowed* — a workspace or project owner must opt in.

Requires `projects:view`.

Operation id: `get_project_sdk_settings_v1_projects__tenant_slug___project_ref__sdk_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the generation settings in force for a project. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_ref}/sdk-settings` {#put-project-sdk-settings-v1-projects-tenant-slug-project-ref-sdk-settings-put}

**Set this project's generation settings**

Save an override for one project, replacing whatever it held. The workspace defaults still supply every key this body does not name.

Settings are merged **key by key**, tenant first: a project that overrides only its user-agent still inherits its tenant's package patterns. `packageNamePatterns` merges one ecosystem at a time.

A key **absent** from a body inherits the next scope up; a key present as **`null`** is deliberately none, and blocks that inheritance.

Patterns may contain the tokens `{tenant}`, `{project}`, `{version}`, `{year}`, substituted from the scope being resolved. A package pattern is validated by resolving it against probe values and checking the result against its registry's naming rules, so `@acme/{project}-sdk` is accepted and `@ACME/{project}` is not.

Ecosystems: `npm`, `pypi`, `gomod`. `licenseHeader` is capped at 4,000 characters; `userAgent` at 200 and to characters legal in an HTTP header.

`publicSdkEnabled` (boolean, default `false`) is the SDK-3.3 gate: it opens the public browse portal's **Get SDK** client-kit download and its anonymous per-operation snippets for the project. It is the one setting that is an access control rather than branding, so an unset value means *not allowed* — a workspace or project owner must opt in.

Requires `projects:edit`. Audited as `governance.sdk_generation_settings.update`.

Operation id: `put_project_sdk_settings_v1_projects__tenant_slug___project_ref__sdk_settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set this project's generation settings.

- `application/json` — [`SdkGenerationSettingsPutRequest`](#schema-sdkgenerationsettingsputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set this project's generation settings. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 404 | Project not found in this tenant. | — |
| 422 | The settings body is not valid. | — |

## `DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-settings` {#delete-project-sdk-settings-v1-projects-tenant-slug-project-ref-sdk-settings-delete}

**Drop this project's override**

Remove the project's settings, so it inherits the workspace defaults again. Returns the settings **now** in force, not a bare `204`, so a caller can see what it fell back to.

Requires `projects:edit`. Audited as `governance.sdk_generation_settings.clear`.

Operation id: `delete_project_sdk_settings_v1_projects__tenant_slug___project_ref__sdk_settings_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for drop this project's override. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SdkGenerationSettingsOut` {#schema-sdkgenerationsettingsout}

The settings in force for a scope, and where each part of them came from.

Attributes:
    schema_version: The body shape these settings were read as.
    source: ``default`` (nothing saved anywhere), ``tenant``, ``project``, or ``merged`` when
        both scopes contributed.
    content_fingerprint: ``sha256:`` digest of the merged body — identical settings produce
        identical artifacts, and this is the value that proves it.
    settings: The merged settings themselves.
    resolved: The settings with their tokens substituted for this scope, ready to apply.
    scope: The scope this request addressed (``tenant`` or ``project``).
    scope_body: The body saved at *exactly* that scope, verbatim, or ``None`` when nothing is
        saved there. An editor needs this and not just ``settings``: only the raw body says
        whether a key is absent (inherit) or present as ``null`` (deliberately none), and the
        merged view cannot tell those apart.
    tenant_settings_id: The contributing tenant-scope row, when there is one.
    project_settings_id: The contributing project-scope row, when there is one.
    updated_at: When the most specific contributing row was last written.
    updated_by: Who wrote it.
    degraded: True when a stored row could not be read and was skipped.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | The settings body shape. |
| `source` | string | yes | default \| tenant \| project \| merged. |
| `contentFingerprint` | string | yes | sha256 digest of the merged settings body. |
| `settings` | `SdkGenerationSettings` | no | Settings. |
| `resolved` | `ResolvedBrandingOut` | yes | The settings with tokens substituted for this scope. |
| `scope` | string | no | The scope this request addressed: tenant \| project. |
| `scopeBody` | object or null | no | The body saved at exactly this scope, verbatim, or null when nothing is saved here. Only this distinguishes an absent key (inherit) from an explicit null (deliberately none). |
| `tenantSettingsId` | string or null | no | Tenant Settings ID. |
| `projectSettingsId` | string or null | no | Project Settings ID. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |
| `degraded` | boolean | no | True when a stored row could not be read and was skipped. |

### `SdkGenerationSettingsPutRequest` {#schema-sdkgenerationsettingsputrequest}

Body for saving SDK generation settings.

Attributes:
    settings: The ``sdk.generation-settings.v1`` body. Only the keys it names are stored.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `settings` | object | no | The settings to save. Only the keys named here are stored, so a body naming one setting configures exactly that one and leaves the rest inheriting. |
