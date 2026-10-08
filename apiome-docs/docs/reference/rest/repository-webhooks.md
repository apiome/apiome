---
title: "Repository webhooks"
description: "REST endpoints tagged repository-webhooks: 1 operation."
sidebar_position: 53
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `repository-webhooks` · 1 operation

## `POST /v1/repositories/webhook/{provider}` {#ingest-repository-webhook-v1-repositories-webhook-provider-post}

**Ingest a provider push / pull-request webhook delivery**

Receive one signed provider delivery and turn it into a poll (REPO-4.3).

Args:
    request: The inbound request; its **raw** body is what the signature covers, so it is
        read as bytes and never re-serialised from parsed JSON.
    provider: The provider path segment.

Returns:
    A thin receipt: the outcome, its reason code, and how many scan jobs were queued.

Raises:
    HTTPException: 400 for an unsupported provider or an unusable body; 401 when the
        signature does not verify for a repository registered here; 403 when the source
        address is not on the allowlist (REPO-7.6) — raised before any verification.

Operation id: `ingest_repository_webhook_v1_repositories_webhook__provider__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `provider` | path | string | yes | Git provider that signed this delivery: github \| gitlab \| bitbucket |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ingest a provider push / pull-request webhook delivery. | `application/json` [`RepositoryWebhookReceiptResponse`](#schema-repositorywebhookreceiptresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RepositoryWebhookReceiptResponse` {#schema-repositorywebhookreceiptresponse}

What the ingestion endpoint tells a provider it did (REPO-4.3, #2781).

Kept deliberately thin. A provider only needs to know the delivery was accepted so it
stops retrying; anything richer would be a side channel describing a tenant's
repositories to whoever can reach the endpoint.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `accepted` | boolean | no | Accepted. |
| `outcome` | string | yes | Outcome. |
| `reason` | string or null | no | Reason. |
| `jobsEnqueued` | integer | no | Jobs Enqueued. |
