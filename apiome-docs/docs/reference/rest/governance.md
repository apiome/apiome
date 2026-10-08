---
title: "Governance"
description: "REST endpoints tagged governance: 25 operations."
sidebar_position: 25
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `governance` · 25 operations

## `GET /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#get-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-get}

**Read the tenant's API change check suite policy**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Requires `projects:view`.

Operation id: `get_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#put-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-put}

**Save the tenant's API change check suite policy**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.update`.

Operation id: `put_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the tenant's api change check suite policy.

- `application/json` — [`CheckSuitePolicyPutRequest`](#schema-checksuitepolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#delete-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-delete}

**Clear the tenant's API change check suite policy**

Drop the tenant-wide policy so the documented default governs. Project overrides are left in place. Returns the policy now in force.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.clear`.

Operation id: `delete_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for clear the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/deploy-gate-policy` {#get-tenant-gate-policy-v1-tenants-tenant-slug-governance-deploy-gate-policy-get}

**Get the tenant's deploy-gate policy**

The thresholds every project in this tenant is judged under unless it saves its own override. A tenant that has never saved one gets the documented default with `source: "default"`.

Thresholds are **two-rung**: each signal carries a warn threshold and a fail threshold, either of which may be `null` to disable that rung. Absent keys take their documented defaults, so a body naming one threshold configures exactly that one.

The default policy fails on a breaking change and on a broken consumer, and warns on a lint grade below B or a verification older than a day.

Requires `versions:view`.

Operation id: `get_tenant_gate_policy_v1_tenants__tenant_slug__governance_deploy_gate_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the tenant's deploy-gate policy. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/deploy-gate-policy` {#put-tenant-gate-policy-v1-tenants-tenant-slug-governance-deploy-gate-policy-put}

**Set the tenant's deploy-gate thresholds**

Save the tenant-wide policy, replacing whatever it held. Project overrides are left alone: they were configured deliberately, and a tenant-wide edit that silently reset them would move bars nobody asked to move.

Thresholds are **two-rung**: each signal carries a warn threshold and a fail threshold, either of which may be `null` to disable that rung. Absent keys take their documented defaults, so a body naming one threshold configures exactly that one.

The default policy fails on a breaking change and on a broken consumer, and warns on a lint grade below B or a verification older than a day.

Requires `verification_targets:edit`. Audited as `governance.deploy_gate_policy.update`.

Operation id: `put_tenant_gate_policy_v1_tenants__tenant_slug__governance_deploy_gate_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set the tenant's deploy-gate thresholds.

- `application/json` — [`DeployGatePolicyPutRequest`](#schema-deploygatepolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set the tenant's deploy-gate thresholds. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 422 | The threshold body is not valid. | — |

## `DELETE /v1/tenants/{tenant_slug}/governance/deploy-gate-policy` {#delete-tenant-gate-policy-v1-tenants-tenant-slug-governance-deploy-gate-policy-delete}

**Remove the tenant's deploy-gate policy**

Drop the tenant-wide policy so the documented default governs again. Project overrides are not cascaded away.

Requires `verification_targets:delete`. Audited as `governance.deploy_gate_policy.clear`.

Operation id: `delete_tenant_gate_policy_v1_tenants__tenant_slug__governance_deploy_gate_policy_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove the tenant's deploy-gate policy. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/quality-policy` {#get-quality-policy-v1-tenants-tenant-slug-governance-quality-policy-get}

**Get the tenant's import/export quality policy**

The quality policy in force for this tenant (IXH-2.3). A tenant that has never saved one gets the documented default — no floors, advisory only, override permitted — with ``isDefault: true``, so an upgrade changes no behaviour.

Readable by any tenant member: the import wizard renders the verdict it produces, and a user who cannot see the policy cannot understand why a commit was refused.

Operation id: `get_quality_policy_v1_tenants__tenant_slug__governance_quality_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the tenant's import/export quality policy. | `application/json` [`QualityPolicyOut`](#schema-qualitypolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/quality-policy` {#put-quality-policy-v1-tenants-tenant-slug-governance-quality-policy-put}

**Save a new version of the tenant's import/export quality policy**

Append a new policy version (IXH-2.3). Policy rows are immutable so that a verdict recorded against a version stays reproducible; omitted sections carry forward from the current version.

Tenant administrators only. The change is written to the access audit with the full policy body.

Operation id: `put_quality_policy_v1_tenants__tenant_slug__governance_quality_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a new version of the tenant's import/export quality policy.

- `application/json` — [`QualityPolicyPutRequest`](#schema-qualitypolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a new version of the tenant's import/export quality policy. | `application/json` [`QualityPolicyOut`](#schema-qualitypolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/quality-policy/versions` {#list-quality-policy-versions-v1-tenants-tenant-slug-governance-quality-policy-versions-get}

**List saved quality-policy versions**

The tenant's saved policy versions, newest first. Policy rows are immutable, so this is the change history: every verdict names the ``policyVersionId`` it applied.

Operation id: `list_quality_policy_versions_v1_tenants__tenant_slug__governance_quality_policy_versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Maximum versions to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list saved quality-policy versions. | `application/json` [`QualityPolicyVersionListResponse`](#schema-qualitypolicyversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/quality-waivers` {#list-quality-waivers-v1-tenants-tenant-slug-governance-quality-waivers-get}

**List import/export quality waivers**

The tenant's recorded waivers, newest first (IXH-2.3). By default only waivers that are still honoured are returned; pass ``activeOnly=false`` to include expired ones, which the shared waiver-expiry sweep has already notified on.

Operation id: `list_quality_waivers_v1_tenants__tenant_slug__governance_quality_waivers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `scope` | query | string or null | no | Restrict to 'import' or 'export'; omit for both. |
| `activeOnly` | query | boolean | no | Drop waivers whose expiry has passed. |
| `limit` | query | integer | no | Maximum waivers to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list import/export quality waivers. | `application/json` [`QualityWaiverListResponse`](#schema-qualitywaiverlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/governance/quality-waivers` {#create-quality-waiver-v1-tenants-tenant-slug-governance-quality-waivers-post}

**Record a waiver against a blocking quality verdict**

Record accepted risk so a blocked import (or delivery) may proceed (IXH-2.3). The waiver carries the actor, the reason, the scope, and an expiry of the policy's ``waiverTtlHours``; the gate honours it until then, after which the shared waiver-expiry sweep has already warned the tenant.

Refused with 403 when the policy forbids overrides or does not name the caller's effective role — the check is server-side, so a client cannot grant itself one.

Operation id: `create_quality_waiver_v1_tenants__tenant_slug__governance_quality_waivers_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a waiver against a blocking quality verdict.

- `application/json` — [`QualityWaiverCreateRequest`](#schema-qualitywaivercreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record a waiver against a blocking quality verdict. | `application/json` [`QualityWaiverOut`](#schema-qualitywaiverout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/sdk-generation-settings` {#get-tenant-sdk-settings-v1-tenants-tenant-slug-governance-sdk-generation-settings-get}

**Get the workspace generation defaults**

The package naming, licence header and user-agent every project in the workspace inherits unless it overrides them.

Settings are merged **key by key**, tenant first: a project that overrides only its user-agent still inherits its tenant's package patterns. `packageNamePatterns` merges one ecosystem at a time.

A key **absent** from a body inherits the next scope up; a key present as **`null`** is deliberately none, and blocks that inheritance.

Patterns may contain the tokens `{tenant}`, `{project}`, `{version}`, `{year}`, substituted from the scope being resolved. A package pattern is validated by resolving it against probe values and checking the result against its registry's naming rules, so `@acme/{project}-sdk` is accepted and `@ACME/{project}` is not.

Ecosystems: `npm`, `pypi`, `gomod`. `licenseHeader` is capped at 4,000 characters; `userAgent` at 200 and to characters legal in an HTTP header.

`publicSdkEnabled` (boolean, default `false`) is the SDK-3.3 gate: it opens the public browse portal's **Get SDK** client-kit download and its anonymous per-operation snippets for the project. It is the one setting that is an access control rather than branding, so an unset value means *not allowed* — a workspace or project owner must opt in.

Requires `projects:view`.

Operation id: `get_tenant_sdk_settings_v1_tenants__tenant_slug__governance_sdk_generation_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the workspace generation defaults. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/sdk-generation-settings` {#put-tenant-sdk-settings-v1-tenants-tenant-slug-governance-sdk-generation-settings-put}

**Set the workspace generation defaults**

Save the workspace-wide defaults, replacing whatever they held. Projects that have saved their own override keep it for the keys it names.

Settings are merged **key by key**, tenant first: a project that overrides only its user-agent still inherits its tenant's package patterns. `packageNamePatterns` merges one ecosystem at a time.

A key **absent** from a body inherits the next scope up; a key present as **`null`** is deliberately none, and blocks that inheritance.

Patterns may contain the tokens `{tenant}`, `{project}`, `{version}`, `{year}`, substituted from the scope being resolved. A package pattern is validated by resolving it against probe values and checking the result against its registry's naming rules, so `@acme/{project}-sdk` is accepted and `@ACME/{project}` is not.

Ecosystems: `npm`, `pypi`, `gomod`. `licenseHeader` is capped at 4,000 characters; `userAgent` at 200 and to characters legal in an HTTP header.

`publicSdkEnabled` (boolean, default `false`) is the SDK-3.3 gate: it opens the public browse portal's **Get SDK** client-kit download and its anonymous per-operation snippets for the project. It is the one setting that is an access control rather than branding, so an unset value means *not allowed* — a workspace or project owner must opt in.

Requires `projects:edit`. Audited as `governance.sdk_generation_settings.update`.

Operation id: `put_tenant_sdk_settings_v1_tenants__tenant_slug__governance_sdk_generation_settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set the workspace generation defaults.

- `application/json` — [`SdkGenerationSettingsPutRequest`](#schema-sdkgenerationsettingsputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set the workspace generation defaults. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 422 | The settings body is not valid. | — |

## `DELETE /v1/tenants/{tenant_slug}/governance/sdk-generation-settings` {#delete-tenant-sdk-settings-v1-tenants-tenant-slug-governance-sdk-generation-settings-delete}

**Clear the workspace generation defaults**

Remove the workspace defaults. Project overrides are **not** cascaded away — they were configured deliberately. Returns the settings now in force at workspace scope.

Requires `projects:edit`. Audited as `governance.sdk_generation_settings.clear`.

Operation id: `delete_tenant_sdk_settings_v1_tenants__tenant_slug__governance_sdk_generation_settings_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for clear the workspace generation defaults. | `application/json` [`SdkGenerationSettingsOut`](#schema-sdkgenerationsettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/sdk-registry-credentials` {#list-tenant-registry-credentials-v1-tenants-tenant-slug-governance-sdk-registry-credentials-get}

**List the workspace's package-registry credentials**

A credential is **write-only**: this API stores the token encrypted at rest and never returns it. What comes back is its public scheme prefix (`npm_`, `pypi-`), its length and a truncated SHA-256 — enough to confirm which token is stored, not enough to use it.

A **project** credential replaces the workspace one for that ecosystem. Unlike SDK-3.4's generation settings, credentials do not merge field by field: a token is atomic.

Ecosystems: `npm`, `pypi`. `gomod` is absent because a Go module is released by pushing a tag (SDK-4.2), not by uploading to a registry.

`registryUrl` defaults to the ecosystem's public registry and must be `https://` — a publish token sent over plain HTTP is a token disclosed.

Requires `projects:view`.

Operation id: `list_tenant_registry_credentials_v1_tenants__tenant_slug__governance_sdk_registry_credentials_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the workspace's package-registry credentials. | `application/json` [`RegistryCredentialListResponse`](#schema-registrycredentiallistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/sdk-registry-credentials/{ecosystem}` {#put-tenant-registry-credential-v1-tenants-tenant-slug-governance-sdk-registry-credentials-ecosystem-put}

**Store the workspace's credential for one registry**

A credential is **write-only**: this API stores the token encrypted at rest and never returns it. What comes back is its public scheme prefix (`npm_`, `pypi-`), its length and a truncated SHA-256 — enough to confirm which token is stored, not enough to use it.

A **project** credential replaces the workspace one for that ecosystem. Unlike SDK-3.4's generation settings, credentials do not merge field by field: a token is atomic.

Ecosystems: `npm`, `pypi`. `gomod` is absent because a Go module is released by pushing a tag (SDK-4.2), not by uploading to a registry.

`registryUrl` defaults to the ecosystem's public registry and must be `https://` — a publish token sent over plain HTTP is a token disclosed.

Requires `projects:edit`. Audited as `governance.sdk_registry_credential.update` — the audit row records the token's fingerprint, never the token.

Operation id: `put_tenant_registry_credential_v1_tenants__tenant_slug__governance_sdk_registry_credentials__ecosystem__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for store the workspace's credential for one registry.

- `application/json` — [`RegistryCredentialPutRequest`](#schema-registrycredentialputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for store the workspace's credential for one registry. | `application/json` [`RegistryCredentialOut`](#schema-registrycredentialout) |
| 422 | The token, registry URL or ecosystem is not acceptable. | — |
| 503 | No credential-encryption key is configured on this deployment. | — |

## `DELETE /v1/tenants/{tenant_slug}/governance/sdk-registry-credentials/{ecosystem}` {#delete-tenant-registry-credential-v1-tenants-tenant-slug-governance-sdk-registry-credentials-ecosystem-delete}

**Remove the workspace's credential for one registry**

Nothing cascades: a project that stored its own credential keeps publishing with it.

Requires `projects:edit`. Audited as `governance.sdk_registry_credential.clear`.

Operation id: `delete_tenant_registry_credential_v1_tenants__tenant_slug__governance_sdk_registry_credentials__ecosystem__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove the workspace's credential for one registry. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/secret-scrub-policy` {#get-secret-scrub-policy-v1-tenants-tenant-slug-governance-secret-scrub-policy-get}

**Get the tenant's intake secret-scrub policy**

The secret-scrub policy in force for this tenant (MFI-29.6). A tenant that has never saved one gets the documented default — enforce, with entropy detection on — with ``isDefault: true``, which is the behaviour every tenant already had, so an upgrade changes nothing.

Readable by any tenant member: an import summary reports what was redacted, and a user who cannot see the policy cannot understand why.

Operation id: `get_secret_scrub_policy_v1_tenants__tenant_slug__governance_secret_scrub_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the tenant's intake secret-scrub policy. | `application/json` [`SecretScrubPolicyOut`](#schema-secretscrubpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/secret-scrub-policy` {#put-secret-scrub-policy-v1-tenants-tenant-slug-governance-secret-scrub-policy-put}

**Save a new version of the tenant's intake secret-scrub policy**

Append a new policy version (MFI-29.6). Policy rows are immutable so that an import summary recorded against a version stays reproducible; omitted fields carry forward from the current version.

Tenant administrators only, and audited with the full policy body: switching to ``warn_only`` means uploaded credentials persist unredacted, which must be attributable. Note that the collection and captured-traffic formats listed in ``alwaysEnforcedFormats`` stay enforced unless a per-format override says otherwise.

Operation id: `put_secret_scrub_policy_v1_tenants__tenant_slug__governance_secret_scrub_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a new version of the tenant's intake secret-scrub policy.

- `application/json` — [`SecretScrubPolicyPutRequest`](#schema-secretscrubpolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a new version of the tenant's intake secret-scrub policy. | `application/json` [`SecretScrubPolicyOut`](#schema-secretscrubpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/secret-scrub-policy/versions` {#list-secret-scrub-policy-versions-v1-tenants-tenant-slug-governance-secret-scrub-policy-versions-get}

**List saved secret-scrub policy versions**

The tenant's saved scrub-policy versions, newest first. Policy rows are immutable, so this is the change history: every import summary names the ``policyVersionId`` that governed it.

Operation id: `list_secret_scrub_policy_versions_v1_tenants__tenant_slug__governance_secret_scrub_policy_versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Maximum versions to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list saved secret-scrub policy versions. | `application/json` [`SecretScrubPolicyVersionListResponse`](#schema-secretscrubpolicyversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/verification-policy` {#get-verification-policy-v1-tenants-tenant-slug-governance-verification-policy-get}

**Get the tenant's evidence-backed verification policy**

The publish/deploy verification policy in force (ECA-3.1). A tenant that has never saved one gets the documented default — advisory, no required digests, warn on whole-spec breaking — with ``isDefault: true``.

Operation id: `get_verification_policy_v1_tenants__tenant_slug__governance_verification_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the tenant's evidence-backed verification policy. | `application/json` [`VerificationPolicyOut`](#schema-verificationpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/verification-policy` {#put-verification-policy-v1-tenants-tenant-slug-governance-verification-policy-put}

**Save a new version of the tenant's verification policy**

Append a new policy version (ECA-3.1). Rows are immutable. Omitted fields carry forward from the current version. Tenant administrators only.

Operation id: `put_verification_policy_v1_tenants__tenant_slug__governance_verification_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a new version of the tenant's verification policy.

- `application/json` — [`VerificationPolicyPutRequest`](#schema-verificationpolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a new version of the tenant's verification policy. | `application/json` [`VerificationPolicyOut`](#schema-verificationpolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/governance/verification-policy/evaluate` {#evaluate-verification-policy-route-v1-tenants-tenant-slug-governance-verification-policy-evaluate-post}

**Evaluate publish/deploy policy against evidence**

Evaluate the tenant's verification policy for a subject revision. The decision cites exact ECA-1.3 evidence run IDs, persists an evaluation row, and is the same payload the dashboard and publish precheck consume. Breaking findings are whole-spec via version changelogs (#4475); consumer-aware acknowledgment is #4479.

Operation id: `evaluate_verification_policy_route_v1_tenants__tenant_slug__governance_verification_policy_evaluate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for evaluate publish/deploy policy against evidence.

- `application/json` — [`VerificationPolicyEvaluateRequest`](#schema-verificationpolicyevaluaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for evaluate publish/deploy policy against evidence. | `application/json` [`VerificationPolicyDecisionOut`](#schema-verificationpolicydecisionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/verification-policy/evaluations` {#list-verification-policy-evaluations-route-v1-tenants-tenant-slug-governance-verification-policy-evaluations-get}

**List recent verification-policy evaluations**

Operation id: `list_verification_policy_evaluations_route_v1_tenants__tenant_slug__governance_verification_policy_evaluations_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `versionRecordId` | query | string or null | no | Optional catalog revision filter. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list recent verification-policy evaluations. | `application/json` [`VerificationPolicyEvaluationListResponse`](#schema-verificationpolicyevaluationlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/governance/verification-policy/versions` {#list-verification-policy-versions-v1-tenants-tenant-slug-governance-verification-policy-versions-get}

**List saved verification-policy versions**

Operation id: `list_verification_policy_versions_v1_tenants__tenant_slug__governance_verification_policy_versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list saved verification-policy versions. | `application/json` [`VerificationPolicyVersionListResponse`](#schema-verificationpolicyversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CheckSuitePolicyOut` {#schema-checksuitepolicyout}

The suite policy in force for a scope.

Attributes:
    schema_version: :data:`POLICY_SCHEMA_VERSION`.
    source: ``default`` (nothing saved), ``tenant`` or ``project``.
    policy_id: The stored row; ``None`` for the documented default.
    content_fingerprint: Digest of the body.
    policy: The body itself.
    updated_at: When the stored policy last changed.
    updated_by: Who changed it.
    degraded: True when a saved policy could not be read and the default stood in, so
        "nothing is configured" and "I could not read what is" stay distinguishable.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `source` | string | yes | `default` \| `tenant` \| `project`. |
| `policyId` | string or null | no | Policy ID. |
| `contentFingerprint` | string | no | Content Fingerprint. |
| `policy` | `CheckSuitePolicy` | no | Policy. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |
| `degraded` | boolean | no | Degraded. |

### `CheckSuitePolicyPutRequest` {#schema-checksuitepolicyputrequest}

Body for saving a suite policy — the ``gnc.check-suite-policy.v1`` document.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `components` | map of string | no | component → `required` \| `advisory` \| `off`; absent components take defaults. |
| `requiredForPublish` | boolean | no | Require a passing suite evaluation of the current content to publish. |

### `DeployGatePolicyOut` {#schema-deploygatepolicyout}

The threshold policy a gate response was judged under.

Attributes:
    source: ``default`` (nothing saved), ``tenant``, or ``project``.
    policy_id: Stored row id; ``None`` for the documented default.
    content_fingerprint: Digest of the threshold body.
    thresholds: The thresholds themselves.
    updated_at: When the stored policy last changed.
    updated_by: Who changed it.
    degraded: True when a saved policy could not be read and the default stood in. A gate has
        to answer, so an unreadable policy row falls back rather than failing — but a caller
        must be able to tell "nothing is configured" from "I could not read what is".

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `source` | string | yes | `default` \| `tenant` \| `project`. |
| `policyId` | string or null | no | Policy ID. |
| `contentFingerprint` | string | no | Content Fingerprint. |
| `thresholds` | `DeployGateThresholds` | no | Thresholds. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |
| `degraded` | boolean | no | True when a saved policy could not be read and the default stood in. |

### `DeployGatePolicyPutRequest` {#schema-deploygatepolicyputrequest}

Body for saving a deploy-gate policy.

Attributes:
    thresholds: The ``ctg.gate-policy.v1`` threshold body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `thresholds` | object | no | Per-signal warn/fail thresholds. Absent groups and absent keys take their documented defaults. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `QualityPolicyOut` {#schema-qualitypolicyout}

The tenant's import/export quality policy in force (IXH-2.3, #5098).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policyVersionId` | string or null | no | Row id of the applied policy version; null when the tenant has none saved. |
| `versionNumber` | integer | no | Monotonic version number; 0 for the built-in default. |
| `contentFingerprint` | string | no | SHA-256 over the canonicalized policy body ('default' for the default). |
| `isDefault` | boolean | no | True when no tenant policy is saved and the advisory default applies. |
| `import` | `QualityPolicyThresholdsOut` | no | Floors applied to import intake. |
| `export` | `QualityPolicyThresholdsOut` | no | Floors applied to export delivery. |
| `formatOverrides` | object | no | Per-adapter-key overrides, e.g. {'openapi': {'import': {'minGrade': 'B'}}}. Resolution is format override → tenant → default. |
| `allowOverride` | boolean | no | Whether a blocking verdict may be waived at all. |
| `overrideRoles` | array of string | no | Role slugs permitted to record a waiver (empty = nobody may). |
| `waiverTtlHours` | integer | no | Lifetime of a granted waiver, in hours. |
| `actorLabel` | string or null | no | Who saved this version. |
| `createdAt` | string (date-time) or string or null | no | When this version was saved. |

### `QualityPolicyPutRequest` {#schema-qualitypolicyputrequest}

Replace the tenant's import/export quality policy (IXH-2.3, #5098).

A PUT always appends a **new version**: policy rows are immutable so a verdict recorded
against a version stays reproducible. Omitted sections keep the values the current policy
holds, so a caller can raise the import floor without restating the export contract.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `import` | `QualityPolicyThresholdsOut` or null | no | Import. |
| `export` | `QualityPolicyThresholdsOut` or null | no | Export. |
| `formatOverrides` | object or null | no | Format Overrides. |
| `allowOverride` | boolean or null | no | Allow Override. |
| `overrideRoles` | array of string or null | no | Override Roles. |
| `waiverTtlHours` | integer or null | no | Waiver Ttl Hours. |

### `QualityPolicyVersionListResponse` {#schema-qualitypolicyversionlistresponse}

The tenant's saved policy versions, newest first (IXH-2.3, #5098).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`QualityPolicyOut`](#schema-qualitypolicyout) | no | Versions. |
| `count` | integer | no | Number of count. |

### `QualityWaiverCreateRequest` {#schema-qualitywaivercreaterequest}

Record a waiver against a blocking quality verdict (IXH-2.3, #5098).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `scope` | enum `"import"`, `"export"` | no | Which gate the waiver applies to. |
| `subjectKey` | string | yes | Subject identity: the SHA-256 of the candidate document for an import (the pre-flight report's cache.content_hash), or the delivery subject for an export. |
| `reason` | string | yes | The actor's stated justification for accepting the risk. |
| `subjectLabel` | string or null | no | Display label for the waived subject (filename / artifact name). |
| `formatKey` | string or null | no | Adapter key / export target the waiver applies to. |
| `reportFingerprint` | string or null | no | Fingerprint of the lint report being waived. |
| `score` | integer or null | no | Lint score at waiver time. |
| `grade` | string or null | no | Lint grade at waiver time. |

### `QualityWaiverListResponse` {#schema-qualitywaiverlistresponse}

A tenant's quality waivers, newest first (IXH-2.3, #5098).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `waivers` | array of [`QualityWaiverOut`](#schema-qualitywaiverout) | no | Waivers. |
| `count` | integer | no | Number of count. |

### `QualityWaiverOut` {#schema-qualitywaiverout}

One recorded quality waiver (IXH-2.3, #5098).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `scope` | string | yes | Scope. |
| `subjectKey` | string | yes | Subject Key. |
| `subjectLabel` | string or null | no | Subject Label. |
| `formatKey` | string or null | no | Format Key. |
| `reportFingerprint` | string or null | no | Report Fingerprint. |
| `score` | integer or null | no | Score. |
| `grade` | string or null | no | Grade. |
| `reason` | string | yes | Reason. |
| `expiresAt` | string (date-time) or string or null | no | Expires At. |
| `policyVersionId` | string or null | no | Policy Version ID. |
| `policyContentFingerprint` | string or null | no | Policy Content Fingerprint. |
| `actorLabel` | string or null | no | Actor Label. |
| `actorRole` | string or null | no | Actor Role. |
| `createdAt` | string (date-time) or string or null | no | Created At. |

### `RegistryCredentialListResponse` {#schema-registrycredentiallistresponse}

The credentials configured for one scope.

Attributes:
    schema_version: The projection's shape.
    scope: The scope that was addressed.
    encryption_configured: Whether this deployment can store credentials at all.
    ecosystems: Which ecosystems can be published to.
    credentials: One entry per stored credential, tenant-wide first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `scope` | string | yes | Scope. |
| `encryptionConfigured` | boolean | yes | Encryption Configured. |
| `ecosystems` | array of string | yes | Ecosystems. |
| `credentials` | array of [`RegistryCredentialOut`](#schema-registrycredentialout) | yes | Credentials. |

### `RegistryCredentialOut` {#schema-registrycredentialout}

A stored credential, described without being revealed.

Attributes:
    schema_version: The projection's shape.
    ecosystem: ``npm`` or ``pypi``.
    scope: ``tenant`` or ``project``.
    project_id: The project this credential belongs to, when it is a project override.
    registry_url: Where it publishes.
    token_prefix: The public scheme prefix the token declares, when it declares one.
    token_length: How many characters the stored token has.
    token_fingerprint: A truncated SHA-256 of the token, for confirming a rotation.
    key_version: Which master key sealed it.
    readable: Whether the stored token can currently be decrypted. ``False`` means the key
        that sealed it is not configured — the credential is present but unusable, and saying
        so beats a publish failing with a decryption error.
    created_at: When it was first stored.
    updated_at: When it was last replaced.
    updated_by: Who last replaced it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `ecosystem` | string | yes | ``npm`` or ``pypi``. |
| `scope` | string | yes | ``tenant`` or ``project``. |
| `projectId` | string or null | no | Project ID. |
| `registryUrl` | string | yes | Registry URL. |
| `tokenPrefix` | string or null | no | Token Prefix. |
| `tokenLength` | integer or null | no | Token Length. |
| `tokenFingerprint` | string or null | no | Token Fingerprint. |
| `keyVersion` | integer or null | no | Key Version. |
| `readable` | boolean | no | Readable. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `RegistryCredentialPutRequest` {#schema-registrycredentialputrequest}

Body for storing a registry credential.

Attributes:
    token: The plaintext registry token. Sealed before it is written and never returned.
    registry_url: Where to publish; defaults to the ecosystem's public registry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | The registry token — an npm automation token or a PyPI API token. Stored envelope-encrypted; never returned by any route. |
| `registryUrl` | string or null | no | Registry endpoint. Defaults to `npm` → `https://registry.npmjs.org`, `pypi` → `https://upload.pypi.org/legacy/`. Must be `https://`. |

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

### `SecretScrubPolicyOut` {#schema-secretscrubpolicyout}

The tenant's intake secret-scrub policy in force (MFI-29.6, #4393).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policyVersionId` | string or null | no | Row id of the applied policy version; null when the tenant has none saved. |
| `versionNumber` | integer | no | Monotonic version number; 0 for the built-in default. |
| `contentFingerprint` | string | no | SHA-256 over the canonicalized policy body ('default' for the default). |
| `isDefault` | boolean | no | True when no tenant policy is saved and the enforce default applies. |
| `mode` | enum `"enforce"`, `"warn_only"` | no | 'enforce' redacts credential values from the source intake persists; 'warn_only' reports the same findings and stores the content unmodified. |
| `entropyDetection` | boolean | no | Whether the high-entropy heuristic runs alongside the named credential patterns. The named patterns always run and cannot be disabled. |
| `formatOverrides` | object | no | Per-adapter-key mode overrides, e.g. {'openapi': {'mode': 'warn_only'}}. Resolution is format override → format default → tenant → default. |
| `alwaysEnforcedFormats` | array of string | no | Adapter keys that resolve to 'enforce' regardless of the tenant mode — the collection and captured-traffic formats. A per-format override still wins. |
| `actorLabel` | string or null | no | Human-readable actor who saved this version. |
| `createdAt` | string (date-time) or null | no | When the version was saved; null for the built-in default. |

### `SecretScrubPolicyPutRequest` {#schema-secretscrubpolicyputrequest}

Replace the tenant's intake secret-scrub policy (MFI-29.6, #4393).

A PUT always appends a **new version**: policy rows are immutable so a job summary
recorded against a version stays reproducible. Omitted fields keep the values the current
policy holds.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"enforce"`, `"warn_only"` or null | no | The tenant-tier scrub mode. |
| `entropyDetection` | boolean or null | no | Whether the high-entropy heuristic runs. |
| `formatOverrides` | object or null | no | Per-adapter-key mode overrides; replaces the map wholesale when given. |

### `SecretScrubPolicyVersionListResponse` {#schema-secretscrubpolicyversionlistresponse}

The tenant's saved secret-scrub policy versions, newest first (MFI-29.6, #4393).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`SecretScrubPolicyOut`](#schema-secretscrubpolicyout) | no | Versions. |
| `count` | integer | no | Number of count. |

### `VerificationPolicyDecisionOut` {#schema-verificationpolicydecisionout}

Auditable evaluate decision shared by API, publish precheck, and dashboard.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `passed` | boolean | yes | Passed. |
| `enforcement` | string | yes | Enforcement. |
| `policyVersionId` | string or null | no | Policy Version ID. |
| `policyContentFingerprint` | string | yes | Policy Content Fingerprint. |
| `evaluationId` | string or null | no | Evaluation ID. |
| `evidenceRunIds` | array of string | no | Evidence Run IDs. |
| `gateResults` | array of `VerificationPolicyGateResultOut` | no | Gate Results. |
| `warnings` | array of object | no | Warnings. |
| `purpose` | string | yes | Purpose. |
| `skipped` | boolean | no | Skipped. |

### `VerificationPolicyEvaluateRequest` {#schema-verificationpolicyevaluaterequest}

Evaluate publish/deploy policy for a subject revision (ECA-3.1, #4734).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `purpose` | string | yes | Evaluate purpose: publish or deploy. |
| `projectSlug` | string or null | no | Project slug (required with versionSlug, or when resolving versionId). |
| `projectId` | string or null | no | Project ID. |
| `versionId` | string or null | no | Catalog revision UUID (versions.id). |
| `versionSlug` | string or null | no | Version slug within the project (e.g. 1.2.0). |

### `VerificationPolicyEvaluationListResponse` {#schema-verificationpolicyevaluationlistresponse}

Recent verification-policy evaluations.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `evaluations` | array of `VerificationPolicyEvaluationOut` | no | Evaluations. |
| `count` | integer | no | Number of count. |

### `VerificationPolicyOut` {#schema-verificationpolicyout}

The tenant's evidence-backed publish/deploy policy in force (ECA-3.1, #4734).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policyVersionId` | string or null | no | Row id of the applied policy version; null when the tenant has none saved. |
| `versionNumber` | integer | no | Monotonic version number; 0 for the built-in default. |
| `contentFingerprint` | string | no | SHA-256 over the canonicalized policy body. |
| `isDefault` | boolean | no | True when no tenant policy is saved and the advisory default applies. |
| `requiredSuiteDigests` | array of string | no | ECA-1.1 suite digests that must have recent passing evidence. |
| `maxEvidenceAgeSeconds` | integer or null | no | Maximum age of cited evidence in seconds; null = no freshness gate. |
| `requiredTargetNetworkClass` | string or null | no | Optional public/private filter on cited evidence. |
| `purpose` | string | no | Which evaluate purposes this policy covers: publish, deploy, or both. |
| `breakingChangeAction` | string | no | Whole-spec breaking posture: ignore, warn, or block (#4475; not consumer-aware). |
| `enforcement` | string | no | advisory = report only; block = refuse publish/deploy when evaluate fails. |
| `actorLabel` | string or null | no | Who saved this version. |
| `createdAt` | string (date-time) or string or null | no | When this version was saved. |

### `VerificationPolicyPutRequest` {#schema-verificationpolicyputrequest}

Append a new evidence-backed verification policy version (ECA-3.1, #4734).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `requiredSuiteDigests` | array of string or null | no | ECA-1.1 digests (sha256:&lt;64 hex&gt;); omit to keep the current list. |
| `maxEvidenceAgeSeconds` | integer or null | no | Freshness ceiling in seconds; omit to keep current; send null via clear flag. |
| `clearMaxEvidenceAgeSeconds` | boolean | no | When true, clears maxEvidenceAgeSeconds even if omitted. |
| `requiredTargetNetworkClass` | string or null | no | Required Target Network Class. |
| `clearRequiredTargetNetworkClass` | boolean | no | When true, clears the network-class filter. |
| `purpose` | string or null | no | publish, deploy, or both; omit to keep current. |
| `breakingChangeAction` | string or null | no | Breaking Change Action. |
| `enforcement` | string or null | no | advisory or block; omit to keep current. |

### `VerificationPolicyVersionListResponse` {#schema-verificationpolicyversionlistresponse}

Saved verification-policy versions, newest first (ECA-3.1, #4734).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`VerificationPolicyOut`](#schema-verificationpolicyout) | no | Versions. |
| `count` | integer | no | Number of count. |
