---
title: "Admin auth providers"
description: "REST endpoints tagged admin-auth-providers: 3 operations."
sidebar_position: 3
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `admin-auth-providers` · 3 operations

## `GET /v1/admin/auth-providers` {#list-auth-providers-v1-admin-auth-providers-get}

**List Auth Providers**

List every registry provider with its masked stored config (OLO-8.4).

One entry per known provider (including ``coming-soon`` placeholders), in registry display
order, overlaying any stored row. Secrets are never included — each entry reports only
``secret_set`` and, per field, whether it is DB-sourced or falls back to env.

Returns:
    The provider list. Providers with no stored row are reported entirely as env-fallback.

Operation id: `list_auth_providers_v1_admin_auth_providers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list auth providers. | `application/json` [`ProviderConfigListResponse`](#schema-providerconfiglistresponse) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/admin/auth-providers/{provider_id}` {#update-auth-provider-v1-admin-auth-providers-provider-id-put}

**Update Auth Provider**

Create or update one provider's config (OLO-8.4).

Applies a partial update (see :class:`ProviderConfigUpdateRequest`): omitted fields are left
as stored, explicitly-null fields are cleared to env-fallback, and a non-blank ``client_secret``
is sealed (OLO-8.3) and stored write-only. When the effective post-write state has the provider
``enabled``, required-field completeness is enforced first — an incomplete or ``coming-soon``
provider is rejected with a structured ``422`` before anything is written.

Args:
    provider_id: Provider slug from the path; must exist in the registry.
    payload: The partial update.

Returns:
    The provider's masked view after the write (never carrying the secret).

Raises:
    HTTPException: ``404`` unknown provider; ``422`` incomplete/ineligible enablement;
        ``503`` when a secret is supplied but encryption is unconfigured.

Operation id: `update_auth_provider_v1_admin_auth_providers__provider_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for update auth provider.

- `application/json` — [`ProviderConfigUpdateRequest`](#schema-providerconfigupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update auth provider. | `application/json` [`ProviderConfigView`](#schema-providerconfigview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | Unknown provider id (not in the registry). | — |
| 422 | Enabling a provider that is coming-soon or missing required fields. | — |
| 503 | A secret was supplied but secret encryption is not configured. | — |

## `DELETE /v1/admin/auth-providers/{provider_id}` {#delete-auth-provider-v1-admin-auth-providers-provider-id-delete}

**Delete Auth Provider**

Remove one provider's stored configuration entirely (OLO-8.7).

Drops the whole ``auth_provider_config`` row, returning the provider to env-only governance
(OLO-8.5) as if it had never been configured — including its ``enabled`` override, so sign-in
enablement is once again derived from the environment. **The sealed client secret is destroyed
with the row and cannot be recovered**; re-configuring the provider means re-entering it.

Deleting is **idempotent**: a provider with no stored row is already in the requested end
state, so it succeeds rather than 404ing. The ``404`` is reserved for a slug that is not in the
registry at all, matching PUT — that is a caller error, not an absent row.

Returns the provider's post-delete view (rather than ``204``) for two reasons: it matches what
PUT returns, so the admin UI can swap one view for another without a re-fetch; and an empty
``204`` body would force every JSON-parsing client on the path — notably the apiome-ui proxy —
to special-case this route.

Args:
    provider_id: Provider slug from the path; must exist in the registry.

Returns:
    The provider's masked view after removal — every field reported as env-fallback.

Raises:
    HTTPException: ``404`` when the provider id is not in the registry.

Operation id: `delete_auth_provider_v1_admin_auth_providers__provider_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider_id` | path | string | yes | Path parameter identifying the provider id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete auth provider. | `application/json` [`ProviderConfigView`](#schema-providerconfigview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | Unknown provider id (not in the registry). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProviderConfigListResponse` {#schema-providerconfiglistresponse}

Payload of ``GET /v1/admin/auth-providers``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `providers` | array of [`ProviderConfigView`](#schema-providerconfigview) | no | Providers. |

### `ProviderConfigUpdateRequest` {#schema-providerconfigupdaterequest}

Body of ``PUT /v1/admin/auth-providers/{provider_id}`` — a partial update.

Every field is optional and interpreted by **presence** (``model_fields_set``), so the admin UI
can change one field without disturbing the others:

* a field **omitted** from the body is left exactly as stored;
* a field sent as ``null`` (or, for the string fields, blank) is **cleared** — the provider then
  falls back to env for it (OLO-8.5);
* ``client_secret`` is **write-only**: a non-blank value is sealed (OLO-8.3) and stored; ``null``
  / blank clears the stored secret; omitting it leaves the stored secret untouched. It is never
  returned in any response.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean or null | no | Enable toggle; null clears it (enablement becomes env-derived). |
| `client_id` | string or null | no | OAuth client id; null/blank clears it (falls back to env). |
| `client_secret` | string or null | no | Write-only OAuth client secret; sealed and stored. null/blank clears it. Never returned. |
| `config` | object or null | no | Non-secret provider extras (JSONB); null clears them to an empty object. |

### `ProviderConfigView` {#schema-providerconfigview}

One provider's masked configuration — the shape both GET and PUT return.

Never carries a secret value: ``secret_set`` reports only whether a secret is stored.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider_id` | string | yes | Provider slug (e.g. 'github'). |
| `label` | string | yes | Human-readable provider name. |
| `status` | string | yes | Registry lifecycle: 'available' or 'coming-soon'. |
| `enabled` | boolean or null | no | Explicit enable toggle from the DB. null ⇒ no DB value; enablement is env-derived (OLO-8.5). |
| `enabled_source` | string | yes | 'db' when the enable toggle is stored, else 'env-fallback'. |
| `client_id` | string or null | no | OAuth client id from the DB; null when it falls back to env. |
| `client_id_source` | string | yes | 'db' when a client id is stored, else 'env-fallback'. |
| `secret_set` | boolean | yes | Whether a client secret is stored (encrypted). The secret itself is never returned. |
| `secret_source` | string | yes | 'db' when a secret is stored, else 'env-fallback'. |
| `config` | object | no | Non-secret provider extras (JSONB); empty object when none are stored. |
| `required_fields` | array of string | no | Fields that must be present for this provider to be enabled (empty for coming-soon). |
| `missing_for_enable` | array of string | no | Required fields not yet satisfied by the DB row; enabling is blocked while non-empty. |
| `can_enable` | boolean | yes | True when the provider is 'available' and all required fields are present in the DB. |
| `updated_at` | string (date-time) or null | no | When the row was last changed; null when no row exists. |
| `updated_by` | string or null | no | Super-admin who last changed the row; null when no row exists. |
