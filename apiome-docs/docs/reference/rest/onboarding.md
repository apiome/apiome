---
title: "Onboarding"
description: "REST endpoints tagged onboarding: 5 operations."
sidebar_position: 42
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `onboarding` · 5 operations

## `POST /v1/onboarding/first-tenant` {#provision-first-tenant-v1-onboarding-first-tenant-post}

**Provision First Tenant**

Atomically provision the caller's first tenant (or next, when their
entitlement allows more than one).

All-or-nothing: any failure rolls back every write. A second call for a
user already at their ``max_tenants`` cap returns 403 ``tenant-cap-reached``
(the license enforcement guard, OLO-5.3 #4213).

Operation id: `provision_first_tenant_v1_onboarding_first_tenant_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for provision first tenant.

- `application/json` — [`FirstTenantProvisionRequest`](#schema-firsttenantprovisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for provision first tenant. | `application/json` [`FirstTenantProvisionResponse`](#schema-firsttenantprovisionresponse) |
| 400 | Invalid organization name or slug. | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | API-key sessions cannot provision tenants, or (structured, OLO-5.3) ``tenant-cap-reached`` when the caller is at their max-tenants entitlement. | — |
| 409 | Structured conflict: ``tenant-slug-taken`` when the slug is already in use. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Structured throttle (OLO-7.1): ``auth-rate-limited`` when the caller's per-IP or per-account auth budget is spent; carries ``Retry-After``. | — |

## `POST /v1/onboarding/membership-activation` {#activate-membership-v1-onboarding-membership-activation-post}

**Activate Membership**

Activate the caller's *pending* membership in a tenant (invited-user
first arrival, OLO-4.4).

Idempotent: an already-active membership returns 200
``already-active``. Only ``pending`` rows are touched — a ``suspended``
membership returns 403 ``membership-suspended`` and stays suspended.

Operation id: `activate_membership_v1_onboarding_membership_activation_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for activate membership.

- `application/json` — [`MembershipActivationRequest`](#schema-membershipactivationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for activate membership. | `application/json` [`MembershipActivationResponse`](#schema-membershipactivationresponse) |
| 400 | ``tenant_id`` is missing or not a UUID. | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | API-key sessions cannot activate memberships, or the membership is ``suspended`` (structured code ``membership-suspended``) — logging in never unsuspends. | — |
| 404 | The caller has no membership in this tenant (structured code ``membership-not-found``). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Structured throttle (OLO-7.1): ``auth-rate-limited`` when the caller's per-IP or per-account auth budget is spent; carries ``Retry-After``. | — |

## `GET /v1/onboarding/wizard-state` {#get-wizard-state-v1-onboarding-wizard-state-get}

**Get Wizard State**

Return the caller's saved onboarding-wizard state, or 204 when none.

Called when the wizard mounts so an abandoned-then-resumed session reopens
on the step the user left off, with any entered organization name/slug
pre-filled (OLO-4.5, #4209). An expired row reads as absent.

Operation id: `get_wizard_state_v1_onboarding_wizard_state_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The caller's saved onboarding-wizard resume state. | `application/json` [`WizardStateResponse`](#schema-wizardstateresponse) |
| 204 | No saved state (nothing to resume). | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | API-key sessions have no wizard to resume. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Structured throttle (OLO-7.1): ``auth-rate-limited``. | — |

## `PUT /v1/onboarding/wizard-state` {#put-wizard-state-v1-onboarding-wizard-state-put}

**Put Wizard State**

Persist the caller's wizard resume position and record a funnel event.

Called on every wizard step change: the resume row is upserted so a
logout/login reopens here, and — when ``event`` is supplied (``reached`` on
forward navigation, ``completed`` at the end) — a funnel telemetry event is
appended for onboarding metrics. Back navigation persists without an event
so a step is not double-counted (OLO-4.5, #4209).

Operation id: `put_wizard_state_v1_onboarding_wizard_state_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put wizard state.

- `application/json` — [`WizardStateUpsertRequest`](#schema-wizardstateupsertrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Resume state saved (and funnel event recorded when supplied). | — |
| 400 | ``step`` is not a recognized wizard step. | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | API-key sessions cannot drive the onboarding wizard. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Structured throttle (OLO-7.1): ``auth-rate-limited``. | — |

## `DELETE /v1/onboarding/wizard-state` {#delete-wizard-state-v1-onboarding-wizard-state-delete}

**Delete Wizard State**

Clear the caller's saved wizard state (called once the wizard completes).

A provisioned tenant means the wizard no longer shows, so its resume row is
removed rather than left to expire. Idempotent: clearing an already-absent
state is a no-op 204 (OLO-4.5, #4209).

Operation id: `delete_wizard_state_v1_onboarding_wizard_state_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Resume state cleared (or already absent). | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | API-key sessions cannot drive the onboarding wizard. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Structured throttle (OLO-7.1): ``auth-rate-limited``. | — |

## Schemas used {#schemas-used}

### `FirstTenantProvisionRequest` {#schema-firsttenantprovisionrequest}

Body of ``POST /v1/onboarding/first-tenant`` (OLO-4.3, #4207).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Organization display name. |
| `slug` | string or null | no | Tenant slug; derived from the name when omitted or blank. |
| `provision_sample_project` | boolean | no | Seed the curated sample project into the new tenant (best-effort). |

### `FirstTenantProvisionResponse` {#schema-firsttenantprovisionresponse}

Result of ``POST /v1/onboarding/first-tenant``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant` | `TenantProvisionedSchema` | yes | Tenant. |
| `sample_project_id` | string or null | no | Id of the seeded sample project; null when skipped or unavailable. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MembershipActivationRequest` {#schema-membershipactivationrequest}

Body of ``POST /v1/onboarding/membership-activation`` (OLO-4.4, #4208).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_id` | string | yes | Tenant whose pending membership should be activated for the caller. |

### `MembershipActivationResponse` {#schema-membershipactivationresponse}

Result of ``POST /v1/onboarding/membership-activation``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | enum `"activated"`, `"already-active"` | yes | ``activated`` when a pending membership transitioned to active, ``already-active`` when there was nothing to do. |
| `tenant_id` | string | yes | Tenant the membership belongs to. |

### `WizardStateResponse` {#schema-wizardstateresponse}

Persisted onboarding-wizard resume state (``GET /v1/onboarding/wizard-state``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `step` | string | yes | Wizard step to reopen on. |
| `org_name` | string or null | no | Organization display name entered so far, if any. |
| `slug` | string or null | no | Tenant slug entered so far, if any. |
| `updated_at` | string or null | no | ISO-8601 time the state was last saved. |

### `WizardStateUpsertRequest` {#schema-wizardstateupsertrequest}

Body of ``PUT /v1/onboarding/wizard-state`` (OLO-4.5, #4209).

Persists the caller's onboarding-wizard resume position and, when ``event``
is supplied, records a funnel telemetry event for the step. ``org_name`` and
``slug`` carry whatever the user has entered so far so a resumed wizard can
pre-fill them; both are null until the organization step.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `step` | string | yes | Wizard step the user is now on (welcome, organization, summary, done). |
| `org_name` | string or null | no | Organization display name entered so far; null before the organization step. |
| `slug` | string or null | no | Tenant slug entered so far; null before the organization step. |
| `event` | enum `"reached"`, `"completed"`, `"abandoned"` or null | no | Funnel event to record for this step: ``reached`` on forward navigation, omitted when only persisting the resume position (e.g. navigating back). |
