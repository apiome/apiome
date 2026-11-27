---
title: "Usage"
description: "REST endpoints tagged usage: 10 operations."
sidebar_position: 118
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.700.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `usage` · 10 operations

## `PATCH /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/body-samples` {#patch-toolset-body-samples-v1-tenants-tenant-slug-agent-toolsets-toolset-id-body-samples-patch}

**Open or close an agent toolset's body capture**

The AGX-3.3 opt-in that keeps the bodies of a fraction of an agent toolset's `tools/call` invocations for debugging, in the same shape as a usage source's `bodySamples`: a `rate` (at most 1) and an `until` at most 7 days ahead. Opening a window requires the exact `acknowledgement` sentence. `rate: 0` closes it.

Requires `api_keys:edit`, like every toolset setting. Audited as `agent.toolset.body_samples.update`, before and after.

Operation id: `patch_toolset_body_samples_v1_tenants__tenant_slug__agent_toolsets__toolset_id__body_samples_patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open or close an agent toolset's body capture.

- `application/json` — [`BodySampleWindow`](#schema-bodysamplewindow)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for open or close an agent toolset's body capture. | `application/json` [`ToolsetBodySamplesOut`](#schema-toolsetbodysamplesout) |
| 404 | `agent-toolset-not-found`. | — |
| 422 | `usage-body-samples-invalid` or `usage-body-samples-acknowledgement-required`. | — |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/usage/export` {#export-usage-v1-tenants-tenant-slug-projects-project-ref-usage-export-get}

**Export the project's usage rollups**

Stream the project's **daily usage rollups** for the last `days` UTC days (ending today) as `csv` or `json`: one row per day, environment, source, version, operation, status and consumer, with calls, errors, latency and bytes. The consumer is its slug, or `anonymous` for traffic no binding attributes. A binding's name, value or hash is never exported.

The JSON document ends with `totals` (`rows`, `calls`, `errors`), the same sums the adoption views show for the window.

Requires `versions:view`. Audited as `usage.export`.

Operation id: `export_usage_v1_tenants__tenant_slug__projects__project_ref__usage_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `format` | query | enum `"csv"`, `"json"` | no | `csv` or `json`. |
| `days` | query | integer | no | Window in UTC days, ending today. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The export, streamed as an attachment. | `application/json` any; `text/csv` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/usage/sources` {#list-usage-sources-v1-tenants-tenant-slug-projects-project-ref-usage-sources-get}

**List the project's usage sources and agent toolsets**

Everything that can keep this project's traffic: each **usage source** with its head sampling, field capture and body samples (at most 5 %, at most 7 days ahead), and each **agent toolset** with its AGX-3.3 body capture (at most 7 days ahead). Both opt-ins use one shape, `bodySamples`, and the sentence that opens a window is `acknowledgement`.

Requires `projects:view`.

Operation id: `list_usage_sources_v1_tenants__tenant_slug__projects__project_ref__usage_sources_get`

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
| 200 | Successful response for list the project's usage sources and agent toolsets. | `application/json` [`UsageSourceList`](#schema-usagesourcelist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/projects/{project_ref}/usage/sources/{source_id}` {#patch-usage-source-v1-tenants-tenant-slug-projects-project-ref-usage-sources-source-id-patch}

**Change what a usage source captures**

Set head sampling (`samplingRate`, in (0, 1]), field capture (`fieldCapture`: field names, never values) and/or body samples (`bodySamples`). A body-sample window takes a `rate` of at most 0.05 and an `until` at most 7 days ahead, and opening one requires the exact `acknowledgement` sentence (`422 usage-body-samples-acknowledgement-required`). `rate: 0` closes it.

Requires `projects:edit`. Audited as `usage.source.update`, before and after.

Operation id: `patch_usage_source_v1_tenants__tenant_slug__projects__project_ref__usage_sources__source_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `source_id` | path | string | yes | Path parameter identifying the source id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change what a usage source captures.

- `application/json` — [`UsageSourceUpdate`](#schema-usagesourceupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change what a usage source captures. | `application/json` [`UsageSourceOut`](#schema-usagesourceout) |
| 404 | `usage-source-not-found`. | — |
| 422 | `usage-body-samples-invalid`, `usage-body-samples-acknowledgement-required` or `usage-settings-unchanged`. | — |

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

## `GET /v1/tenants/{tenant_slug}/usage/retention` {#get-usage-retention-v1-tenants-tenant-slug-usage-retention-get}

**Read the workspace's usage retention**

How long the usage index keeps **hourly counters** and **daily rollups**: the tier's caps (`usage_hourly_retention_days`, `usage_rollup_retention_days`; `-1` keeps rows forever), the workspace's own values (`null` uses the cap), and what the nightly purge applies (the smaller of the two). Body samples are purged after 7 days whatever the tier.

Requires `projects:view`.

Operation id: `get_usage_retention_v1_tenants__tenant_slug__usage_retention_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the workspace's usage retention. | `application/json` [`UsageRetentionResponse`](#schema-usageretentionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/usage/retention` {#put-usage-retention-v1-tenants-tenant-slug-usage-retention-put}

**Lower the workspace's usage retention**

Keep usage counters for **fewer** days than the tier allows. A value above the cap is refused (`422 usage-retention-above-cap`, the message names the cap). `null` goes back to the cap. The next nightly purge deletes what is now past retention.

Requires `members:edit` (Owner and Admin). Audited as `usage.retention.update`.

Operation id: `put_usage_retention_v1_tenants__tenant_slug__usage_retention_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for lower the workspace's usage retention.

- `application/json` — [`RetentionUpdate`](#schema-retentionupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lower the workspace's usage retention. | `application/json` [`UsageRetentionResponse`](#schema-usageretentionresponse) |
| 422 | `usage-retention-above-cap`, or a value below 1. | — |

## `POST /v1/tenants/{tenant_slug}/usage/sdk-beacon` {#report-sdk-beacon-v1-tenants-tenant-slug-usage-sdk-beacon-post}

**Report SDK compatibility beacon counts**

The door an **opted-in** generated SDK reports to (`apiome.sdk.beacon/v1`). Each event is an aggregated count of calls of one operation with one outcome — `ok`, `client_error`, `server_error`, `network` or `incompatible` — and names only the SDK and its version, the API version and published revision the SDK was generated from, and the operation id. There is no field for a body, header, status code, latency, URL, host, credential or caller identifier; unknown keys are refused (`422`).

Counts land on the UTC day the server receives the report. Events naming a revision that is not a published revision of the source's project are rejected by index.

Requires a workspace API key with the `usage:ingest` scope (or full access) and an enabled usage source of kind `sdk_beacon`: `403 usage-source-disabled` when the tenant has switched it off, `409 usage-source-kind-mismatch` for another kind of source.

Operation id: `report_sdk_beacon_v1_tenants__tenant_slug__usage_sdk_beacon_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `X-Apiome-Usage-Source` | header | string or null | no | The `sdk_beacon` usage source. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for report sdk compatibility beacon counts.

- `application/json` — [`SdkBeaconBatch`](#schema-sdkbeaconbatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for report sdk compatibility beacon counts. | `application/json` [`SdkBeaconResponse`](#schema-sdkbeaconresponse) |
| 400 | No source named, or the header and body name different sources. | — |
| 403 | Not a workspace API key, or the source is disabled. | — |
| 404 | Unknown source. | — |
| 409 | `usage-source-kind-mismatch`: the source is not an `sdk_beacon` source. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/usage/sdk-beacons` {#read-sdk-beacons-v1-tenants-tenant-slug-usage-sdk-beacons-get}

**Read a project's SDK beacon counts**

Beacon calls over the last `days` UTC days (default 30, at most 400), grouped by `spec_revision_id`, `api_version`, `sdk_name`, `sdk_version`, `operation_id` and `outcome` — the keys of the SDK kit's compatibility manifest (`manifest.json` → `operations[].operation_id`, built for one published revision) — so incompatibilities can be lined up with the manifest they were generated from.

Requires `consumer_contracts:view`.

Operation id: `read_sdk_beacons_v1_tenants__tenant_slug__usage_sdk_beacons_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project` | query | string | yes | Project slug or id. |
| `days` | query | integer | no | Query parameter: days. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a project's sdk beacon counts. | `application/json` [`SdkBeaconCounts`](#schema-sdkbeaconcounts) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/usage/sources/har` {#resolve-har-usage-source-v1-tenants-tenant-slug-usage-sources-har-post}

**Find or create a project's HAR usage source**

Answers the `har` usage source that `apiome usage upload` posts a HAR file's events to (RDG-1.4).

* With `sourceId`, that source is checked: it must belong to the project and be a `har` source (`409` otherwise).
* Without it, the project's oldest `har` source in the environment is answered, or one is created with field capture on, sampling rate 1 and no body window. A disabled source is refused with `403`, never replaced.

Takes a workspace API key with the `usage:ingest` scope (or full access), or a session.

Operation id: `resolve_har_usage_source_v1_tenants__tenant_slug__usage_sources_har_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for find or create a project's har usage source.

- `application/json` — [`HarSourceRequest`](#schema-harsourcerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for find or create a project's har usage source. | `application/json` [`HarSourceResponse`](#schema-harsourceresponse) |
| 400 | Invalid or reserved environment. | — |
| 403 | The source is disabled. | — |
| 404 | Unknown project or source. | — |
| 409 | The named source belongs to another project, or is not a `har` source. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BodySampleWindow` {#schema-bodysamplewindow}

Open, change or close a body-sample window.

Set ``rate`` to ``0`` to close it. Opening it takes ``until`` and the exact acknowledgement sentence.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rate` | number | yes | Fraction of exchanges to keep; `0` closes the window. |
| `until` | string (date-time) or null | no | When sampling stops; at most 7 days ahead. |
| `acknowledgement` | string or null | no | Required to open a window: the exact sentence `BODY_SAMPLE_ACKNOWLEDGEMENT` (shown in the UI). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `HarSourceRequest` {#schema-harsourcerequest}

Which project and environment a HAR upload reports, and optionally which source.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project` | string | yes | Project slug or UUID. |
| `environment` | string | yes | The environment the recorded traffic happened in (`prod`, `staging`, ...). `mock` is reserved. |
| `sourceId` | string or null | no | A `har` source of the project to use. Omit it to find the project's source, or create one. |

### `HarSourceResponse` {#schema-harsourceresponse}

The source a HAR upload posts its events to.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sourceId` | string | yes | The `usage_source` to name on `…/usage/ingest`. |
| `projectId` | string | yes | The source's project. |
| `kind` | string | yes | Always `har`. |
| `environment` | string | yes | The source's default environment. |
| `samplingRate` | number | yes | The source's head-sampling rate. |
| `fieldCapture` | boolean | yes | Whether field presence is counted (on for a source created here). |
| `bodySamplesOpen` | boolean | yes | Whether the source accepts opt-in body samples right now (its body window is open). |
| `created` | boolean | yes | Whether this call created the source. |

### `RetentionUpdate` {#schema-retentionupdate}

Body of ``PUT …/usage/retention``. `null` (or an omitted field) goes back to the tier cap.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `hourlyDays` | integer or null | no | Days of hourly counters to keep (at most the cap). |
| `rollupDays` | integer or null | no | Days of daily rollups to keep (at most the cap). |

### `SdkBeaconBatch` {#schema-sdkbeaconbatch}

One report from an SDK.

Attributes:
    schema_id: Always ``apiome.sdk.beacon/v1``.
    source_id: The ``sdk_beacon`` usage source, unless the ``X-Apiome-Usage-Source`` header names it.
    events: The aggregated events.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schema` | `"apiome.sdk.beacon/v1"` | no | Embedded JSON Schema document. |
| `source_id` | string (uuid) or null | no | Source ID. |
| `events` | array of `SdkBeaconEvent` | yes | Events. |

### `SdkBeaconCounts` {#schema-sdkbeaconcounts}

A project's beacon counts over a window.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `days` | integer | yes | Days. |
| `counts` | array of `SdkBeaconCount` | no | Most calls first. |

### `SdkBeaconResponse` {#schema-sdkbeaconresponse}

What happened to a report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source_id` | string | yes | Source ID. |
| `received_at` | string (date-time) | yes | Received At timestamp (ISO 8601). |
| `accepted` | integer | yes | Events counted. |
| `calls` | integer | yes | Calls the counted events stood for. |
| `rejected` | array of `SdkBeaconRejection` | no | Rejected. |

### `ToolsetBodySamplesOut` {#schema-toolsetbodysamplesout}

An agent toolset of the project, with its AGX-3.3 body-capture opt-in.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `versionId` | string | yes | Version ID. |
| `versionLabel` | string or null | no | Version Label. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `bodySamples` | `BodySamples` | yes | Body Samples. |

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

### `UsageRetentionResponse` {#schema-usageretentionresponse}

What the workspace keeps, for how long, and the caps it may lower.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `caps` | `RetentionDays` | yes | The tier's caps. `-1` keeps rows forever. |
| `setting` | `RetentionDays` | yes | The workspace's own values. `null` uses the cap. |
| `effective` | `RetentionDays` | yes | What the nightly purge applies: the smaller of the two. |
| `sampleRetentionDays` | integer | no | Body samples are purged after this many days, whatever the tier. |
| `updatedAt` | string (date-time) or null | no | When the setting last changed. |

### `UsageSourceList` {#schema-usagesourcelist}

The project's sources and agent toolsets: everything that can keep traffic or bodies.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sources` | array of [`UsageSourceOut`](#schema-usagesourceout) | no | Sources. |
| `agentToolsets` | array of [`ToolsetBodySamplesOut`](#schema-toolsetbodysamplesout) | no | Agent Toolsets. |
| `acknowledgement` | string | no | The sentence that opens a body-sample window. |

### `UsageSourceOut` {#schema-usagesourceout}

One traffic source of a project, with what it captures.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `kind` | string | yes | `otlp`, `har`, `access_log`, `mock`, `agent` or `sdk_beacon`. |
| `environment` | string | yes | Environment. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `samplingRate` | number | yes | Head sampling: fraction (0..1] of events kept. |
| `fieldCapture` | boolean | yes | Whether field presence (names, never values) is counted. |
| `bodySamples` | `BodySamples` | yes | Body Samples. |
| `lastReceivedAt` | string (date-time) or null | no | Last Received At. |

### `UsageSourceUpdate` {#schema-usagesourceupdate}

Body of ``PATCH …/usage/sources/{id}``. At least one field is required.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `samplingRate` | number or null | no | Head sampling, in (0, 1]. |
| `fieldCapture` | boolean or null | no | Field Capture. |
| `bodySamples` | [`BodySampleWindow`](#schema-bodysamplewindow) or null | no | Body Samples. |
