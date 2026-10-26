---
title: "Sso"
description: "REST endpoints tagged sso: 8 operations."
sidebar_position: 87
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.315.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sso` · 8 operations

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

Attach an email domain, unverified. A domain belongs to one provider installation-wide.

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
| 409 | `sso-domain-claimed`. | — |
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

Mark a domain verified on the admin's word (DNS verification arrives in EID-1.2).

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
| 422 | Refused with a stable `sso-*` code: `{error, message}`. | — |

## Schemas used {#schemas-used}

### `SsoDomainCreateRequest` {#schema-ssodomaincreaterequest}

Body of ``POST /v1/admin/sso/providers/{id}/domains``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `domain` | string | yes | An email domain such as acme.com (an address is accepted). |

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
| `tenant_id` | string or null | no | The workspace this IdP signs in to. |
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
