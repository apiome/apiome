---
title: "Usage"
description: "REST endpoints tagged usage: 1 operation."
sidebar_position: 83
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.247.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `usage` · 1 operation

## `POST /v1/tenants/{tenant_slug}/usage/ingest` {#ingest-usage-v1-tenants-tenant-slug-usage-ingest-post}

**Ingest a batch of usage events**

The usage index's one door (RDG-1.2). Each event runs through the pipeline in order and stops at its first refusal:

1. **Tier cap** — `usage_events_per_day` of the workspace's license. Over it, the whole batch is answered `429 usage-quota-exceeded` with `retryAt` and ledgered as rejected.
2. **Head sampling** — a deterministic hash of `(source, observed_at, path, status)` against the source's `sampling_rate`; counts are scaled by the inverse rate (`basis: sampled`).
3. **Scrubbing** — path segments that look like a credential, an email or a UUID become `{param}`; query values are discarded and names kept; the user agent is scrubbed and truncated.
4. **Template matching** against the project's **published** revisions — `/pets/42` lands on `GET /pets/{petId}`. Unmatched traffic is counted by inferred template.
5. **Ledger** — one row per batch; this response echoes it.

Requires a workspace API key with the `usage:ingest` scope (or full access). A batch carrying a `sample` is refused with `422 usage-body-not-accepted` unless the source's body window is open.

Operation id: `ingest_usage_v1_tenants__tenant_slug__usage_ingest_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `X-Apiome-Usage-Source` | header | string (uuid) | no | The usage source, when the body has no `source_id`. |

**Request body** (required)

A batch of at most 5000 `apiome.usage.event/v1` events, at most 2097152 bytes (send `Content-Encoding: gzip` to compress it; the limit applies before and after decompression).

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source_id` | string (uuid) | no | The usage source (or send the `X-Apiome-Usage-Source` header). |
| `events` | array of object | yes | Events. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ingest a batch of usage events. | `application/json` [`UsageIngestResponse`](#schema-usageingestresponse) |
| 400 | Malformed batch, unknown encoding, or no source named. | — |
| 403 | Not a workspace API key, or the source is disabled. | — |
| 404 | Unknown source. | — |
| 413 | Over 2 MiB or 5,000 events. | — |
| 422 | `usage-body-not-accepted`: a sample was sent while the body window is closed. | — |
| 429 | `usage-quota-exceeded`: over today's cap; `retryAt` says when it resets. | — |

## Schemas used {#schemas-used}

### `UsageIngestResponse` {#schema-usageingestresponse}

The ledger row of an admitted batch, echoed back.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `batchId` | string | yes | The `usage_ingest_batch` ledger row. |
| `sourceId` | string | yes | The source the batch was filed under. |
| `receivedAt` | string (date-time) | yes | When the batch was ledgered. |
| `received` | integer | yes | Events in the batch. |
| `accepted` | integer | yes | Kept by sampling and matched to an operation of a published revision. |
| `attributed` | integer | no | Of the accepted events, how many a consumer binding attributed to a consumer (RDG-1.8). The rest are counted under the reserved `anonymous` consumer, never dropped. |
| `sampledOut` | integer | yes | Dropped by head sampling. |
| `unmatched` | integer | yes | Kept, but no published revision declares the operation; counted by inferred template. |
| `rejected` | integer | yes | Refused; see `rejections`. |
| `scrubFindings` | integer | yes | Strings the edge scrub rewrote or dropped (a count, never what was found). |
| `basis` | string | yes | `complete` at sampling rate 1; `sampled` when counts were scaled by the inverse rate. |
| `samplingRate` | number | yes | The source's head-sampling rate. |
| `samples` | `UsageIngestSamples` | yes | Samples. |
| `rejections` | array of `UsageIngestRejection` | yes | Per-event rejections, at most 100 (the counts cover every event). |
| `rejectionsTruncated` | boolean | yes | Whether `rejections` was cut short. |
