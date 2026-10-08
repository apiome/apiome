---
title: "SDK regen"
description: "REST endpoints tagged sdk-regen: 7 operations."
sidebar_position: 60
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sdk-regen` · 7 operations

## `POST /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-jobs/{job_id}/retry` {#retry-regen-job-v1-projects-tenant-slug-project-ref-sdk-regen-jobs-job-id-retry-post}

**Retry a dead-lettered regen job**

Puts a `dead_letter` job back on the queue with a fresh attempt budget. It runs with the subscription as it is now, and skips any step that already succeeded — a job that published its package and then failed to open its pull request only delivers on the retry, pinned to the version it already published.

Refused with `409` when the job is not dead-lettered, or when its subscription was removed or disabled (unsubscribing stops future runs, retries included).

Requires `versions:publish`. Audited as `sdk.regen_job.retry`.

Operation id: `retry_regen_job_v1_projects__tenant_slug___project_ref__sdk_regen_jobs__job_id__retry_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for retry a dead-lettered regen job. | `application/json` [`RegenJobModel`](#schema-regenjobmodel) |
| 404 | Project or job not found in this tenant. | — |
| 409 | The job is not dead-lettered, or its subscription is not active. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-runs` {#list-regen-runs-v1-projects-tenant-slug-project-ref-sdk-regen-runs-get}

**List what each publish regenerated and delivered**

One entry per publish that had an active subscription, newest first, each with its jobs: what the job did, the SDK-4.1 publish run it wrote (package, version, archive digest) and the SDK-4.2 delivery run (pull request), with links to both, and every attempt.

`status=dead_letter` lists the dead letter: runs with at least one job that failed permanently or spent its attempts, each retryable with `POST …/sdk-regen-jobs/{jobId}/retry`.

Requires `versions:view`.

Operation id: `list_regen_runs_v1_projects__tenant_slug___project_ref__sdk_regen_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `status` | query | string or null | no | Only runs with a job in this status: pending, running, retrying, succeeded, dead_letter, cancelled. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list what each publish regenerated and delivered. | `application/json` [`RegenRunListResponse`](#schema-regenrunlistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | An unknown job status filter. | — |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-runs/{run_id}` {#get-regen-run-v1-projects-tenant-slug-project-ref-sdk-regen-runs-run-id-get}

**Read what one publish regenerated and delivered**

The run and every job in it.

Requires `versions:view`.

Operation id: `get_regen_run_v1_projects__tenant_slug___project_ref__sdk_regen_runs__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read what one publish regenerated and delivered. | `application/json` [`RegenRunModel`](#schema-regenrunmodel) |
| 404 | Project or run not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-subscriptions` {#list-regen-subscriptions-v1-projects-tenant-slug-project-ref-sdk-regen-subscriptions-get}

**List which of a project's SDKs regenerate on publish**

A **regen subscription** makes one of a project's SDKs regenerate and ship every time the project publishes a version — no one has to remember to.

`deliveryMode` says how it ships: `registry` publishes the package (SDK-4.1, using the project's registry credential), `git` opens or updates a pull request (SDK-4.2, using the project's git delivery target), and `registry_and_git` publishes first and then delivers the version that publish claimed. It has **no default**: publishing to a public registry is irreversible, so it is never done unless named.

`options.dryRun` (registry modes only, default `false`) rehearses every release instead: the package is built and the credential resolved, and nothing is uploaded. Unknown options are refused.

Ecosystems: `npm`, `pypi` — one subscription per project per ecosystem.

Requires `projects:view`.

Operation id: `list_regen_subscriptions_v1_projects__tenant_slug___project_ref__sdk_regen_subscriptions_get`

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
| 200 | Successful response for list which of a project's sdks regenerate on publish. | `application/json` [`RegenSubscriptionListResponse`](#schema-regensubscriptionlistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}` {#put-regen-subscription-v1-projects-tenant-slug-project-ref-sdk-regen-subscriptions-ecosystem-put}

**Subscribe a project's SDK for one ecosystem to its publish events**

A **regen subscription** makes one of a project's SDKs regenerate and ship every time the project publishes a version — no one has to remember to.

`deliveryMode` says how it ships: `registry` publishes the package (SDK-4.1, using the project's registry credential), `git` opens or updates a pull request (SDK-4.2, using the project's git delivery target), and `registry_and_git` publishes first and then delivers the version that publish claimed. It has **no default**: publishing to a public registry is irreversible, so it is never done unless named.

`options.dryRun` (registry modes only, default `false`) rehearses every release instead: the package is built and the credential resolved, and nothing is uploaded. Unknown options are refused.

Ecosystems: `npm`, `pypi` — one subscription per project per ecosystem.

Replaces any existing subscription for this project and ecosystem. Jobs already queued run with the subscription as it is when they start.

Requires `projects:edit` **and** `versions:publish` — a subscription publishes and delivers on the tenant's behalf on every later publish. Audited as `sdk.regen_subscription.update`.

Operation id: `put_regen_subscription_v1_projects__tenant_slug___project_ref__sdk_regen_subscriptions__ecosystem__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for subscribe a project's sdk for one ecosystem to its publish events.

- `application/json` — [`RegenSubscriptionPutRequest`](#schema-regensubscriptionputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for subscribe a project's sdk for one ecosystem to its publish events. | `application/json` [`RegenSubscriptionOut`](#schema-regensubscriptionout) |
| 404 | Project not found in this tenant. | — |
| 422 | An invalid ecosystem, delivery mode or option. | — |

## `PATCH /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}` {#patch-regen-subscription-v1-projects-tenant-slug-project-ref-sdk-regen-subscriptions-ecosystem-patch}

**Enable or disable a project's regen subscription**

Disabling keeps the subscription's configuration and stops future runs: jobs already queued for it are cancelled when the worker reaches them, and nothing already published or delivered is touched. Enabling resumes it from the next publish.

Disabling requires `projects:edit`; enabling also requires `versions:publish`. Audited as `sdk.regen_subscription.enable` / `sdk.regen_subscription.disable`.

Operation id: `patch_regen_subscription_v1_projects__tenant_slug___project_ref__sdk_regen_subscriptions__ecosystem__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for enable or disable a project's regen subscription.

- `application/json` — [`RegenSubscriptionPatchRequest`](#schema-regensubscriptionpatchrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for enable or disable a project's regen subscription. | `application/json` [`RegenSubscriptionOut`](#schema-regensubscriptionout) |
| 404 | Project or subscription not found. | — |
| 422 | The ecosystem is not one a subscription can name. | — |

## `DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}` {#delete-regen-subscription-v1-projects-tenant-slug-project-ref-sdk-regen-subscriptions-ecosystem-delete}

**Unsubscribe a project's SDK from its publish events**

Removes the subscription. Future publishes no longer regenerate this SDK, and jobs still queued for it are cancelled. Past runs, jobs, published packages and pull requests are kept.

Requires `projects:edit`. Audited as `sdk.regen_subscription.delete`.

Operation id: `delete_regen_subscription_v1_projects__tenant_slug___project_ref__sdk_regen_subscriptions__ecosystem__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unsubscribe a project's sdk from its publish events. | `application/json` object |
| 404 | Project not found in this tenant. | — |
| 422 | The ecosystem is not one a subscription can name. | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RegenJobModel` {#schema-regenjobmodel}

One subscription's regeneration for one publish.

Attributes:
    job_id: The job.
    run_id: The publish event it belongs to.
    subscription_id: The subscription it ran for; ``null`` once unsubscribed.
    subscription_active: Whether that subscription is enabled now; ``null`` once removed.
    ecosystem: ``npm`` or ``pypi``.
    delivery_mode: The mode the latest attempt ran with.
    options: The options the latest attempt ran with.
    status: ``pending``, ``running``, ``retrying``, ``succeeded``, ``dead_letter`` or
        ``cancelled``.
    attempt_count: Attempts in the current budget.
    max_attempts: The budget.
    next_attempt_at: When a retrying job is next due.
    retryable: Whether ``POST …/retry`` would accept it now.
    publish: The registry step's result, when it ran.
    delivery: The git step's result, when it ran.
    error: The latest failure (or cancellation reason).
    attempts: One record per attempt, each naming the runs it wrote.
    retry_href: Where to retry it, when it is retryable.
    retry_requested_by: Who last retried it.
    retry_requested_at: When.
    created_at: When the publish queued it.
    updated_at: When it last changed.
    finished_at: When it reached its current terminal status.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `jobId` | string | yes | Job ID. |
| `runId` | string | yes | Run ID. |
| `subscriptionId` | string or null | no | Subscription ID. |
| `subscriptionActive` | boolean or null | no | Subscription Active. |
| `ecosystem` | string | yes | Ecosystem. |
| `deliveryMode` | string | yes | Delivery Mode. |
| `options` | object | no | Options. |
| `status` | string | yes | Status. |
| `attemptCount` | integer | yes | Number of attempt. |
| `maxAttempts` | integer | no | Max Attempts. |
| `nextAttemptAt` | string (date-time) or null | no | Next Attempt At. |
| `retryable` | boolean | no | Retryable. |
| `publish` | `RegenPublishStepModel` or null | no | Publish. |
| `delivery` | `RegenDeliveryStepModel` or null | no | Delivery. |
| `error` | `RegenJobErrorModel` or null | no | Error. |
| `attempts` | array of object | no | Attempts. |
| `retryHref` | string or null | no | Retry Href. |
| `retryRequestedBy` | string or null | no | Retry Requested By. |
| `retryRequestedAt` | string (date-time) or null | no | Retry Requested At. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `finishedAt` | string (date-time) or null | no | Finished At. |

### `RegenRunListResponse` {#schema-regenrunlistresponse}

A page of regen history.

Attributes:
    runs: The runs, newest first.
    total: How many runs match.
    limit: The page size used.
    offset: The offset used.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`RegenRunModel`](#schema-regenrunmodel) | yes | Runs. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `RegenRunModel` {#schema-regenrunmodel}

One publish event and the jobs it expanded into.

Attributes:
    run_id: The run.
    status: ``in_progress``, ``succeeded``, ``dead_letter`` or ``cancelled``, read off its jobs.
    version_id: The published revision; ``null`` once deleted.
    version_line: Its version label.
    version_href: The revision.
    published_by: Who published it.
    created_at: When it was published.
    jobs: One per subscription that was active at the time.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string | yes | Run ID. |
| `status` | string | yes | Status. |
| `versionId` | string or null | no | Version ID. |
| `versionLine` | string or null | no | Version Line. |
| `versionHref` | string or null | no | Version Href. |
| `publishedBy` | string or null | no | Published By. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `jobs` | array of [`RegenJobModel`](#schema-regenjobmodel) | no | Jobs. |

### `RegenSubscriptionListResponse` {#schema-regensubscriptionlistresponse}

A project's subscriptions.

Attributes:
    ecosystems: Which ecosystems can be subscribed.
    delivery_modes: Which delivery modes exist.
    subscriptions: One entry per subscribed ecosystem.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystems` | array of string | yes | Ecosystems. |
| `deliveryModes` | array of string | yes | Delivery Modes. |
| `subscriptions` | array of [`RegenSubscriptionOut`](#schema-regensubscriptionout) | yes | Subscriptions. |

### `RegenSubscriptionOut` {#schema-regensubscriptionout}

A subscription, as the API describes it.

Attributes:
    schema_version: The projection's shape.
    ecosystem: ``npm`` or ``pypi``.
    delivery_mode: ``registry``, ``git`` or ``registry_and_git``.
    options: The normalised options (``{"dryRun": …}`` for a registry mode, ``{}`` for git).
    active: Whether publishes regenerate this SDK.
    created_at: When the subscription was first stored.
    updated_at: When it was last changed.
    updated_by: Who last changed it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `ecosystem` | string | yes | Ecosystem. |
| `deliveryMode` | string | yes | Delivery Mode. |
| `options` | object | no | Options. |
| `active` | boolean | no | Active. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `RegenSubscriptionPatchRequest` {#schema-regensubscriptionpatchrequest}

Body for enabling or disabling a subscription.

Attributes:
    active: The new state.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `active` | boolean | yes | `true` to enable, `false` to disable. |

### `RegenSubscriptionPutRequest` {#schema-regensubscriptionputrequest}

Body for storing a subscription.

Attributes:
    delivery_mode: ``registry``, ``git`` or ``registry_and_git``. Required.
    options: The options object (``{"dryRun": true}``), or omitted for the defaults.
    active: Whether publishes regenerate this SDK. Defaults to ``true``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deliveryMode` | string | yes | `registry`, `git` or `registry_and_git`. No default. |
| `options` | object or null | no | `{"dryRun": true}` rehearses registry releases. Registry modes only. |
| `active` | boolean | no | Whether publishes regenerate this SDK. |
