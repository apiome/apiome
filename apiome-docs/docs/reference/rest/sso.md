---
title: "Sso"
description: "REST endpoints tagged sso: 17 operations."
sidebar_position: 106
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.618.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sso` · 17 operations

## `GET /v1/admin/sso/providers` {#list-sso-providers-v1-admin-sso-providers-get}

**List Sso Providers**

List every SSO provider with its domains, newest first. Secrets are never included.

Operation id: `list_sso_providers_v1_admin_sso_providers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list sso providers. | `application/json` [`SsoProviderListResponse`](#schema-ssoproviderlistresponse) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/admin/sso/providers` {#create-sso-provider-v1-admin-sso-providers-post}

**Create Sso Provider**

Register an SSO provider, disabled until it has a verified domain and is enabled.

OIDC: the issuer's discovery document is fetched and checked (issuer match, HTTPS authorize /
token / JWKS endpoints) and the endpoints are stored. SAML: the IdP metadata is parsed safely;
an IdP offering only an unsupported binding is refused with ``sso-binding-unsupported``.

Raises:
    HTTPException: ``422`` with a stable ``sso-*`` code; ``503`` when a secret is given but
        encryption is unconfigured.

Operation id: `create_sso_provider_v1_admin_sso_providers_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for create sso provider.

- `application/json` — [`SsoProviderCreateRequest`](#schema-ssoprovidercreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create sso provider. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |
| 503 | Secret encryption not configured. | — |

## `GET /v1/admin/sso/providers/{provider_id}` {#get-sso-provider-v1-admin-sso-providers-provider-id-get}

**Get Sso Provider**

One SSO provider with its domains. Secrets are never included.

Operation id: `get_sso_provider_v1_admin_sso_providers__provider_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get sso provider. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `PATCH /v1/admin/sso/providers/{provider_id}` {#update-sso-provider-v1-admin-sso-providers-provider-id-patch}

**Update Sso Provider**

Partially update an SSO provider.

Enabling requires a complete provider: an OIDC provider must hold a client secret
(``sso-enable-incomplete`` otherwise). A provider with no verified domain may be enabled but is
not ``routable`` until a domain is verified.

Operation id: `update_sso_provider_v1_admin_sso_providers__provider_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for update sso provider.

- `application/json` — [`SsoProviderUpdateRequest`](#schema-ssoproviderupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update sso provider. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |
| 503 | Secret encryption not configured. | — |

## `DELETE /v1/admin/sso/providers/{provider_id}` {#delete-sso-provider-v1-admin-sso-providers-provider-id-delete}

**Delete Sso Provider**

Remove an SSO provider and its domains. Its sealed secrets are destroyed with it.

Identities already linked through it (``external_auth_providers`` rows ``sso:<slug>``) are kept,
so those users can still sign in another way; the provider simply stops routing.

Operation id: `delete_sso_provider_v1_admin_sso_providers__provider_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete sso provider. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/admin/sso/providers/{provider_id}/domains` {#add-sso-domain-v1-admin-sso-providers-provider-id-domains-post}

**Add Sso Domain**

Attach an email domain, unverified. A domain another provider has verified is refused.

Operation id: `add_sso_domain_v1_admin_sso_providers__provider_id__domains_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for add sso domain.

- `application/json` — [`SsoDomainCreateRequest`](#schema-ssodomaincreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for add sso domain. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider. | — |
| 409 | `sso-domain-claimed` or `sso-domain-exists`. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `DELETE /v1/admin/sso/providers/{provider_id}/domains/{domain}` {#remove-sso-domain-v1-admin-sso-providers-provider-id-domains-domain-delete}

**Remove Sso Domain**

Detach a domain. Sign-ins from it stop routing to this IdP at once.

Operation id: `remove_sso_domain_v1_admin_sso_providers__provider_id__domains__domain__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `domain` | path | string | yes | Path parameter identifying the domain segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove sso domain. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider or domain. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/admin/sso/providers/{provider_id}/domains/{domain}/verify` {#verify-sso-domain-v1-admin-sso-providers-provider-id-domains-domain-verify-post}

**Verify Sso Domain**

Mark a domain verified on the admin's word.

A workspace owner proves a domain with a DNS TXT record instead
(``POST /v1/tenants/{tenant}/sso/providers/{id}/domains/{domain}/verify``).

Operation id: `verify_sso_domain_v1_admin_sso_providers__provider_id__domains__domain__verify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `domain` | path | string | yes | Path parameter identifying the domain segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify sso domain. | `application/json` [`SsoProviderView`](#schema-ssoproviderview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No such provider or domain. | — |
| 409 | `sso-domain-claimed`: another provider has verified this domain. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `GET /v1/tenants/{tenant_slug}/sso/providers` {#list-tenant-sso-providers-v1-tenants-tenant-slug-sso-providers-get}

**List the workspace's SSO providers**

Every identity provider of this workspace with its domains, newest first. Secrets are never included.

Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `list_tenant_sso_providers_v1_tenants__tenant_slug__sso_providers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the workspace's sso providers. | `application/json` [`TenantSsoProviderListResponse`](#schema-tenantssoproviderlistresponse) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/tenants/{tenant_slug}/sso/providers` {#create-tenant-sso-provider-v1-tenants-tenant-slug-sso-providers-post}

**Register an SSO provider**

Register this workspace's identity provider: OIDC by issuer (the discovery document is fetched and checked) or SAML 2.0 by metadata URL or XML. It starts disabled, and routes no sign-in until it is enabled **and** has a verified domain.

Audited as `sso.provider.created`. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `create_tenant_sso_provider_v1_tenants__tenant_slug__sso_providers_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register an sso provider.

- `application/json` — [`TenantSsoProviderCreateRequest`](#schema-tenantssoprovidercreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register an sso provider. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |
| 503 | Secret encryption not configured. | — |

## `GET /v1/tenants/{tenant_slug}/sso/providers/{provider_id}` {#get-tenant-sso-provider-v1-tenants-tenant-slug-sso-providers-provider-id-get}

**Read one SSO provider**

One provider with its domains and how many members sign in through it.

Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `get_tenant_sso_provider_v1_tenants__tenant_slug__sso_providers__provider_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one sso provider. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider in this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `PATCH /v1/tenants/{tenant_slug}/sso/providers/{provider_id}` {#update-tenant-sso-provider-v1-tenants-tenant-slug-sso-providers-provider-id-patch}

**Change an SSO provider**

Partially update a provider; omitted fields are left alone. `enabled: false` stops sign-ins reaching the identity provider at once. Enabling an OIDC provider needs its client secret (`sso-enable-incomplete`).

Audited as `sso.provider.updated` with the names of the changed fields. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `update_tenant_sso_provider_v1_tenants__tenant_slug__sso_providers__provider_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change an sso provider.

- `application/json` — [`TenantSsoProviderUpdateRequest`](#schema-tenantssoproviderupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change an sso provider. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider in this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |
| 503 | Secret encryption not configured. | — |

## `DELETE /v1/tenants/{tenant_slug}/sso/providers/{provider_id}` {#delete-tenant-sso-provider-v1-tenants-tenant-slug-sso-providers-provider-id-delete}

**Remove an SSO provider**

Remove a provider, its domains and its sealed secrets. Members who signed in through it keep their accounts but can no longer sign in this way; `member_count` in the response says how many.

Audited as `sso.provider.deleted`. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `delete_tenant_sso_provider_v1_tenants__tenant_slug__sso_providers__provider_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove an sso provider. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider in this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/tenants/{tenant_slug}/sso/providers/{provider_id}/domains` {#add-tenant-sso-domain-v1-tenants-tenant-slug-sso-providers-provider-id-domains-post}

**Add an email domain**

Attach an email domain, unverified, and issue the DNS challenge for it: publish `verification_token` as a TXT record at `record_name`, then call verify. An unverified domain routes no sign-in.

Refused: a public mailbox domain (`sso-domain-public`), a domain another workspace has verified (`sso-domain-claimed`), a domain already on this provider (`sso-domain-exists`).

Audited as `sso.provider.updated`. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `add_tenant_sso_domain_v1_tenants__tenant_slug__sso_providers__provider_id__domains_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add an email domain.

- `application/json` — [`SsoDomainCreateRequest`](#schema-ssodomaincreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for add an email domain. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider in this workspace. | — |
| 409 | `sso-domain-claimed` or `sso-domain-exists`. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `DELETE /v1/tenants/{tenant_slug}/sso/providers/{provider_id}/domains/{domain}` {#remove-tenant-sso-domain-v1-tenants-tenant-slug-sso-providers-provider-id-domains-domain-delete}

**Remove an email domain**

Detach a domain. Sign-ins from it stop reaching this identity provider at once, and another workspace may then verify it.

Audited as `sso.provider.updated`. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `remove_tenant_sso_domain_v1_tenants__tenant_slug__sso_providers__provider_id__domains__domain__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `domain` | path | string | yes | Path parameter identifying the domain segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove an email domain. | `application/json` [`TenantSsoProviderView`](#schema-tenantssoproviderview) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider or domain in this workspace. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## `POST /v1/tenants/{tenant_slug}/sso/providers/{provider_id}/domains/{domain}/verify` {#verify-tenant-sso-domain-v1-tenants-tenant-slug-sso-providers-provider-id-domains-domain-verify-post}

**Verify an email domain by DNS**

Look up the TXT record `_apiome-challenge.<domain>` and mark the domain verified when it holds the domain's `verification_token`. Always answers `200` with `check.status`:

- `verified` — the domain now routes sign-ins (once the provider is enabled);
- `not-found` — no TXT record at that name yet;
- `mismatch` — a TXT record is there with another value (`check.observed` lists what was found);
- `could-not-check` — the lookup itself failed (`check.observed` says why). Nothing is changed, and the domain is **not** verified.

An already verified domain answers `verified` without a lookup. Limited to three checks an hour per domain.

A successful verification is audited as `sso.domain.verified`. Requires a signed-in owner or tenant administrator; API keys are refused.

Operation id: `verify_tenant_sso_domain_v1_tenants__tenant_slug__sso_providers__provider_id__domains__domain__verify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `domain` | path | string | yes | Path parameter identifying the domain segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify an email domain by dns. | `application/json` [`SsoDomainVerifyResponse`](#schema-ssodomainverifyresponse) |
| 403 | Not a signed-in owner or tenant administrator of this workspace. | — |
| 404 | No such provider or domain in this workspace. | — |
| 409 | `sso-domain-claimed`: another workspace has verified this domain. | — |
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |
| 429 | `sso-verify-rate-limited`: three checks an hour per domain. | — |

## `POST /v1/tenants/{tenant_slug}/sso/providers/{provider_id}/provision` {#provision-tenant-sso-member-v1-tenants-tenant-slug-sso-providers-provider-id-provision-post}

**Provision a member on SSO sign-in (service-to-service)**

Called by apiome-ui with the internal service token after a sign-in through this provider succeeded. Makes that person a member of the provider's workspace, idempotently on `(workspace, user)`, and answers `200` with `outcome`:

- `provisioned` — first sign-in: an active membership with the provider's default role (`viewer` when none is set; never `owner`), recorded as `provisioned_by: sso:<slug>` and audited as `member.provisioned`, source `sso`;
- `activated` — a pending invitation was accepted by signing in; the invited role is kept;
- `existing` — already a member; nothing changes and the member keeps their role;
- `suspended` — the membership is suspended; nothing changes;
- `seat-cap-blocked` — every licensed member seat is in use. **No membership is created**; the block is audited as `member.provision_blocked` and every owner receives a `seat_cap_blocked_sso` notification (once per person per 24 hours).

`{tenant}` is the workspace's id or slug and must be the provider's own workspace: a provider of one workspace cannot provision into another (`404`). Only an account that holds this provider's `sso:<slug>` identity and whose email is in one of the provider's verified domains is provisioned.

Operation id: `provision_tenant_sso_member_v1_tenants__tenant_slug__sso_providers__provider_id__provision_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for provision a member on sso sign-in (service-to-service).

- `application/json` — [`SsoProvisionRequest`](#schema-ssoprovisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for provision a member on sso sign-in (service-to-service). | `application/json` [`SsoProvisionResponse`](#schema-ssoprovisionresponse) |
| 401 | No internal service token presented. | — |
| 403 | Internal service token invalid; or `sso-identity-missing` / `sso-email-domain-mismatch`: this person did not sign in through this provider. | — |
| 404 | `sso-provider-not-found` in this workspace, or `sso-user-not-found`. | — |
| 409 | `sso-provider-disabled`: a disabled provider provisions nobody. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | Internal service path disabled (no INTERNAL_SERVICE_TOKEN). | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SsoDomainCreateRequest` {#schema-ssodomaincreaterequest}

Body of ``POST /v1/admin/sso/providers/{id}/domains``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain` | string | yes | An email domain such as acme.com (an address is accepted). |

### `SsoDomainVerifyResponse` {#schema-ssodomainverifyresponse}

Payload of the verify route: the provider as it now stands, and what the check found.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | [`TenantSsoProviderView`](#schema-tenantssoproviderview) | yes | Provider. |
| `check` | `SsoDomainCheckView` | yes | Check. |

### `SsoProviderCreateRequest` {#schema-ssoprovidercreaterequest}

Body of ``POST /v1/admin/sso/providers``.

OIDC needs ``issuer`` + ``client_id`` + ``client_secret``; SAML needs ``metadata_url`` or
``metadata_xml`` plus ``email_source`` (and ``email_attribute`` when that is ``attribute``).
Secrets are write-only.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `protocol` | string | yes | `oidc` or `saml`. |
| `slug` | string | yes | 2–28 lower-case letters, digits and hyphens. |
| `display_name` | string | yes | Display Name. |
| `tenant_id` | string or null | no | The workspace this IdP signs in to and provisions members into. Required (`sso-tenant-required`). |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | Default Role Slug. |
| `issuer` | string or null | no | OIDC issuer URL (https). |
| `client_id` | string or null | no | Client ID. |
| `client_secret` | string or null | no | Write-only; sealed at rest. Never returned. |
| `metadata_url` | string or null | no | SAML IdP metadata URL (https). |
| `metadata_xml` | string or null | no | SAML IdP metadata XML, pasted. |
| `email_source` | string or null | no | SAML: `nameid` or `attribute`. |
| `email_attribute` | string or null | no | Email Attribute. |
| `sp_private_key` | string or null | no | SAML SP signing key (PEM). Write-only; sealed at rest. |

### `SsoProviderListResponse` {#schema-ssoproviderlistresponse}

Payload of ``GET /v1/admin/sso/providers``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `providers` | array of [`SsoProviderView`](#schema-ssoproviderview) | no | Providers. |

### `SsoProviderUpdateRequest` {#schema-ssoproviderupdaterequest}

Body of ``PATCH /v1/admin/sso/providers/{id}`` — a partial update, by field presence.

An omitted field is left as stored. ``client_secret`` / ``sp_private_key`` are write-only: a
value replaces the sealed secret, ``null`` clears it. Sending ``metadata_url`` or
``metadata_xml`` re-reads the SAML metadata; sending ``client_id`` re-runs OIDC discovery.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `display_name` | string or null | no | Display Name. |
| `tenant_id` | string or null | no | Tenant that owns the resource. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | Default Role Slug. |
| `client_id` | string or null | no | Client ID. |
| `client_secret` | string or null | no | Client Secret. |
| `metadata_url` | string or null | no | Metadata URL. |
| `metadata_xml` | string or null | no | Metadata Xml. |
| `email_source` | string or null | no | Email Source. |
| `email_attribute` | string or null | no | Email Attribute. |
| `sp_private_key` | string or null | no | Sp Private Key. |

### `SsoProviderView` {#schema-ssoproviderview}

A provider as admins see it. Never carries a secret.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `plugin_provider_id` | string | yes | `sso-<slug>`: the id in sign-in URLs. |
| `identity_kind` | string | yes | `sso:<slug>`: the provider recorded on identities and auth events. |
| `protocol` | string | yes | `oidc` or `saml`. |
| `display_name` | string | yes | Display Name. |
| `issuer` | string | yes | OIDC issuer, or the SAML IdP entity id. |
| `tenant_id` | string or null | no | Tenant that owns the resource. |
| `tenant_name` | string or null | no | Tenant Name. |
| `oidc_config` | object or null | no | Client id and discovered endpoints; no secret. |
| `saml_config` | object or null | no | IdP entity id, SSO URL, binding, certificates and email source. |
| `has_client_secret` | boolean | yes | Whether client secret. |
| `has_sp_private_key` | boolean | yes | Whether sp private key. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `routable` | boolean | yes | Enabled and at least one verified domain: sign-ins reach the IdP. |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | Default Role Slug. |
| `domains` | array of `SsoDomainView` | no | Domains. |
| `created_by` | string or null | no | Created By. |
| `updated_by` | string or null | no | Updated By. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or null | no | Last update timestamp (ISO 8601). |

### `SsoProvisionRequest` {#schema-ssoprovisionrequest}

Body of the provision route: who just signed in through the provider.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | yes | The signed-in account's id. |

### `SsoProvisionResponse` {#schema-ssoprovisionresponse}

What provisioning decided for one sign-in.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `outcome` | string | yes | `provisioned`, `activated`, `existing`, `suspended` or `seat-cap-blocked`. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |
| `tenant_name` | string | yes | Tenant Name. |
| `role_slug` | string or null | no | The member's role after the call, if they hold one. |
| `role_name` | string or null | no | Role Name. |
| `seat_limit` | integer or null | no | The workspace's licensed member seats; `null` when seat enforcement is off. |

### `TenantSsoProviderCreateRequest` {#schema-tenantssoprovidercreaterequest}

Body of ``POST /v1/tenants/{t}/sso/providers``.

OIDC needs ``issuer`` + ``client_id`` + ``client_secret``; SAML needs ``metadata_url`` or
``metadata_xml`` plus ``email_source`` (and ``email_attribute`` when that is ``attribute``).
Secrets are write-only. The provider belongs to the caller's workspace.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `protocol` | string | yes | `oidc` or `saml`. |
| `slug` | string | yes | 2–28 lower-case letters, digits and hyphens. Unique installation-wide. |
| `display_name` | string | yes | Display Name. |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | A role of this workspace, other than `owner`. |
| `issuer` | string or null | no | OIDC issuer URL (https). |
| `client_id` | string or null | no | Client ID. |
| `client_secret` | string or null | no | Write-only; sealed at rest. Never returned. |
| `metadata_url` | string or null | no | SAML IdP metadata URL (https). |
| `metadata_xml` | string or null | no | SAML IdP metadata XML, pasted. |
| `email_source` | string or null | no | SAML: `nameid` or `attribute`. |
| `email_attribute` | string or null | no | Email Attribute. |
| `sp_private_key` | string or null | no | SAML SP signing key (PEM). Write-only; sealed at rest. |

### `TenantSsoProviderListResponse` {#schema-tenantssoproviderlistresponse}

Payload of ``GET /v1/tenants/{t}/sso/providers``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `providers` | array of [`TenantSsoProviderView`](#schema-tenantssoproviderview) | no | Providers. |

### `TenantSsoProviderUpdateRequest` {#schema-tenantssoproviderupdaterequest}

Body of ``PATCH /v1/tenants/{t}/sso/providers/{id}`` — a partial update, by field presence.

An omitted field is left as stored. ``client_secret`` / ``sp_private_key`` are write-only: a
value replaces the sealed secret, ``null`` clears it. Sending ``metadata_url`` or
``metadata_xml`` re-reads the SAML metadata; sending ``client_id`` re-runs OIDC discovery.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `display_name` | string or null | no | Display Name. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | Default Role Slug. |
| `client_id` | string or null | no | Client ID. |
| `client_secret` | string or null | no | Client Secret. |
| `metadata_url` | string or null | no | Metadata URL. |
| `metadata_xml` | string or null | no | Metadata Xml. |
| `email_source` | string or null | no | Email Source. |
| `email_attribute` | string or null | no | Email Attribute. |
| `sp_private_key` | string or null | no | Sp Private Key. |

### `TenantSsoProviderView` {#schema-tenantssoproviderview}

A provider as its workspace's owners see it. Never carries a secret.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `plugin_provider_id` | string | yes | `sso-<slug>`: the id in sign-in URLs. |
| `identity_kind` | string | yes | `sso:<slug>`: the provider recorded on identities and auth events. |
| `protocol` | string | yes | `oidc` or `saml`. |
| `display_name` | string | yes | Display Name. |
| `issuer` | string | yes | OIDC issuer, or the SAML IdP entity id. |
| `tenant_id` | string or null | no | Tenant that owns the resource. |
| `tenant_name` | string or null | no | Tenant Name. |
| `oidc_config` | object or null | no | Client id and discovered endpoints; no secret. |
| `saml_config` | object or null | no | IdP entity id, SSO URL, binding, certificates and email source. |
| `has_client_secret` | boolean | yes | Whether client secret. |
| `has_sp_private_key` | boolean | yes | Whether sp private key. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `routable` | boolean | yes | Enabled and at least one verified domain: sign-ins reach the IdP. |
| `preset` | string or null | no | Preset. |
| `default_role_slug` | string or null | no | Default Role Slug. |
| `domains` | array of `SsoDomainView` | no | Domains. |
| `created_by` | string or null | no | Created By. |
| `updated_by` | string or null | no | Updated By. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or null | no | Last update timestamp (ISO 8601). |
| `member_count` | integer | no | Members of this workspace who have signed in through this provider. |
