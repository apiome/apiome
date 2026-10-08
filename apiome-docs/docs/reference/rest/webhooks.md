---
title: "Webhooks"
description: "REST endpoints tagged webhooks: 6 operations."
sidebar_position: 80
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `webhooks` · 6 operations

## `GET /v1/push-webhook-subscriptions/{tenant_slug}` {#list-push-webhook-subscriptions-v1-push-webhook-subscriptions-tenant-slug-get}

**List Push Webhook Subscriptions**

Operation id: `list_push_webhook_subscriptions_v1_push_webhook_subscriptions__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list push webhook subscriptions. | `application/json` array of [`PushWebhookSubscriptionResponse`](#schema-pushwebhooksubscriptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/push-webhook-subscriptions/{tenant_slug}` {#create-push-webhook-subscription-v1-push-webhook-subscriptions-tenant-slug-post}

**Create Push Webhook Subscription**

Operation id: `create_push_webhook_subscription_v1_push_webhook_subscriptions__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create push webhook subscription.

- `application/json` — [`PushWebhookSubscriptionCreateRequest`](#schema-pushwebhooksubscriptioncreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create push webhook subscription. | `application/json` [`PushWebhookSubscriptionResponse`](#schema-pushwebhooksubscriptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/push-webhook-subscriptions/{tenant_slug}/deliveries/dead-letter` {#list-push-webhook-dead-letter-deliveries-v1-push-webhook-subscriptions-tenant-slug-deliveries-dead-letter-get}

**List Push Webhook Dead Letter Deliveries**

List terminal dead-letter webhook deliveries for the tenant (#2588).

Operation id: `list_push_webhook_dead_letter_deliveries_v1_push_webhook_subscriptions__tenant_slug__deliveries_dead_letter_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list push webhook dead letter deliveries. | `application/json` array of [`PushWebhookDeadLetterItem`](#schema-pushwebhookdeadletteritem) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/push-webhook-subscriptions/{tenant_slug}/deliveries/{event_id}` {#get-push-webhook-delivery-detail-v1-push-webhook-subscriptions-tenant-slug-deliveries-event-id-get}

**Get Push Webhook Delivery Detail**

Delivery event with full attempt history (#2588).

Operation id: `get_push_webhook_delivery_detail_v1_push_webhook_subscriptions__tenant_slug__deliveries__event_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `event_id` | path | string | yes | Path parameter identifying the event id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get push webhook delivery detail. | `application/json` [`PushWebhookDeliveryEventDetailResponse`](#schema-pushwebhookdeliveryeventdetailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/push-webhook-subscriptions/{tenant_slug}/{subscription_id}` {#get-push-webhook-subscription-v1-push-webhook-subscriptions-tenant-slug-subscription-id-get}

**Get Push Webhook Subscription**

Operation id: `get_push_webhook_subscription_v1_push_webhook_subscriptions__tenant_slug___subscription_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subscription_id` | path | string | yes | Path parameter identifying the subscription id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get push webhook subscription. | `application/json` [`PushWebhookSubscriptionResponse`](#schema-pushwebhooksubscriptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/push-webhook-subscriptions/{tenant_slug}/{subscription_id}` {#update-push-webhook-subscription-v1-push-webhook-subscriptions-tenant-slug-subscription-id-patch}

**Update Push Webhook Subscription**

Operation id: `update_push_webhook_subscription_v1_push_webhook_subscriptions__tenant_slug___subscription_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subscription_id` | path | string | yes | Path parameter identifying the subscription id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update push webhook subscription.

- `application/json` — [`PushWebhookSubscriptionUpdateRequest`](#schema-pushwebhooksubscriptionupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update push webhook subscription. | `application/json` [`PushWebhookSubscriptionResponse`](#schema-pushwebhooksubscriptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PushWebhookDeadLetterItem` {#schema-pushwebhookdeadletteritem}

Terminal failed delivery (#2588).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `subscriptionId` | string | yes | Subscription ID. |
| `eventType` | string | yes | Event Type. |
| `payload` | object | yes | Payload. |
| `attemptCount` | integer | yes | Number of attempt. |
| `lastError` | string or null | no | Last Error. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `PushWebhookDeliveryEventDetailResponse` {#schema-pushwebhookdeliveryeventdetailresponse}

PushWebhookDeliveryEventDetailResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `subscriptionId` | string | yes | Subscription ID. |
| `eventType` | string | yes | Event Type. |
| `status` | string | yes | Status. |
| `payload` | object | yes | Payload. |
| `attemptCount` | integer | yes | Number of attempt. |
| `nextRetryAt` | string (date-time) or null | no | Next Retry At. |
| `lastError` | string or null | no | Last Error. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `attempts` | array of `PushWebhookDeliveryAttemptItem` | no | Attempts. |

### `PushWebhookSubscriptionCreateRequest` {#schema-pushwebhooksubscriptioncreaterequest}

Create a push webhook subscription (#2587). Plaintext signing secret is write-only.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | yes | HTTPS webhook URL (validated server-side). |
| `signingSecret` | string | yes | Shared secret for signing deliveries; never returned after create. |
| `active` | boolean | no | Whether deliveries are enabled. |
| `minSeverity` | enum `"breaking"`, `"non-breaking"`, `"docs-only"` or null | no | Publish-event severity threshold (CTG-3.3): deliver version.published events only when the classified max severity meets this level. Omit/null to receive every publish event (default; other event types are never filtered). |

### `PushWebhookSubscriptionResponse` {#schema-pushwebhooksubscriptionresponse}

Push webhook subscription — signing secret is never included; only signingSecretRef.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `url` | string | yes | URL. |
| `active` | boolean | yes | Active. |
| `signingSecretRef` | string | yes | Signing Secret Ref. |
| `minSeverity` | enum `"breaking"`, `"non-breaking"`, `"docs-only"` or null | no | Min Severity. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `PushWebhookSubscriptionUpdateRequest` {#schema-pushwebhooksubscriptionupdaterequest}

Update URL, active flag, severity filter, and/or rotate signing secret (#2587, #4477).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string or null | no | New HTTPS URL (must remain unique per tenant). |
| `signingSecret` | string or null | no | Signing Secret. |
| `active` | boolean or null | no | Active. |
| `minSeverity` | enum `"breaking"`, `"non-breaking"`, `"docs-only"` or null | no | Publish-event severity threshold (CTG-3.3). Pass an explicit null to clear the filter (deliver every publish event); omit to leave unchanged. |
