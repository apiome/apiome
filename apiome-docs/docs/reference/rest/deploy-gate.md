---
title: "Deploy gate"
description: "REST endpoints tagged deploy-gate: 4 operations."
sidebar_position: 18
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `deploy-gate` · 4 operations

## `GET /v1/projects/{tenant_slug}/{project_ref}/gate` {#get-project-deploy-gate-v1-projects-tenant-slug-project-ref-gate-get}

**Can I promote this API version?**

One aggregate verdict for a CD pipeline, composed of the four signals that already exist elsewhere in the platform:

* **lint** — the GOV grade stored on the revision (never recomputed here);
* **breaking** — the CTG-3.1 classification of the publish against its predecessor;
* **consumers** — the CTG-4.2 per-consumer verdicts ("breaks 2 of 7");
* **verification** — CTG-4.4 freshness, falling back to a manual CTG-4.3 report.

**Partial inputs are the normal case.** A signal with nothing behind it reports `not_configured` and is excluded from the verdict rather than failing it; a signal that exists but could not be read reports `unknown` and is also excluded, counted apart. `evaluatedSignals` says how many actually took part — branch on that, not on `status`, if a project with nothing configured must not read as a green light.

**The status is always 200.** The verdict lives in `status` (`pass` / `warn` / `fail`); the pipeline owns the exit code.

By default the gate judges the project's newest **published** revision. Pass `revisionId` to judge a specific one.

Requires `versions:view`. The consumer signal additionally needs `consumer_contracts:view`; without it that one signal reports `unknown`.

Operation id: `get_project_deploy_gate_v1_projects__tenant_slug___project_ref__gate_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `revisionId` | query | string or null | no | Judge this published revision instead of the newest one. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for can i promote this api version?. | `application/json` [`DeployGateReport`](#schema-deploygatereport) |
| 400 | The named revision is not published. | — |
| 404 | Project or revision not found in this tenant. | — |
| 409 | The project has no published revision to gate. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/gate/policy` {#get-project-gate-policy-v1-projects-tenant-slug-project-ref-gate-policy-get}

**Get the deploy-gate policy in force for a project**

The thresholds this project's gate is judged under, and where they came from: `project` (an override saved here), `tenant` (the tenant-wide policy), or `default` (nothing saved anywhere).

Thresholds are **two-rung**: each signal carries a warn threshold and a fail threshold, either of which may be `null` to disable that rung. Absent keys take their documented defaults, so a body naming one threshold configures exactly that one.

The default policy fails on a breaking change and on a broken consumer, and warns on a lint grade below B or a verification older than a day.

Readable by anyone who can read the gate — a verdict nobody can explain is not a gate. Requires `versions:view`.

Operation id: `get_project_gate_policy_v1_projects__tenant_slug___project_ref__gate_policy_get`

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
| 200 | Successful response for get the deploy-gate policy in force for a project. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_ref}/gate/policy` {#put-project-gate-policy-v1-projects-tenant-slug-project-ref-gate-policy-put}

**Set this project's deploy-gate thresholds**

Save an override for one project, replacing whatever it held. The tenant-wide policy still governs every project without one.

Thresholds are **two-rung**: each signal carries a warn threshold and a fail threshold, either of which may be `null` to disable that rung. Absent keys take their documented defaults, so a body naming one threshold configures exactly that one.

The default policy fails on a breaking change and on a broken consumer, and warns on a lint grade below B or a verification older than a day.

Requires `verification_targets:edit`: moving the bar is the same class of decision as deciding where verification points. Audited as `governance.deploy_gate_policy.update`.

Operation id: `put_project_gate_policy_v1_projects__tenant_slug___project_ref__gate_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set this project's deploy-gate thresholds.

- `application/json` — [`DeployGatePolicyPutRequest`](#schema-deploygatepolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set this project's deploy-gate thresholds. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 404 | Project not found in this tenant. | — |
| 422 | The threshold body is not valid. | — |

## `DELETE /v1/projects/{tenant_slug}/{project_ref}/gate/policy` {#delete-project-gate-policy-v1-projects-tenant-slug-project-ref-gate-policy-delete}

**Remove this project's deploy-gate override**

Drop the project override so the tenant-wide policy (or the documented default) governs again. Returns the policy that is now in force, so a caller sees what it fell back to rather than having to ask again.

Requires `verification_targets:delete`. Audited as `governance.deploy_gate_policy.clear`.

Operation id: `delete_project_gate_policy_v1_projects__tenant_slug___project_ref__gate_policy_delete`

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
| 200 | Successful response for remove this project's deploy-gate override. | `application/json` [`DeployGatePolicyOut`](#schema-deploygatepolicyout) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

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

### `DeployGateReport` {#schema-deploygatereport}

The single aggregate verdict a CD pipeline reads.

Attributes:
    schema_version: :data:`DEPLOY_GATE_SCHEMA_VERSION`.
    status: ``pass`` / ``warn`` / ``fail`` — the worst *evaluated* signal.
    summary: One line a pipeline can print.
    project_id / project_slug: The gated project.
    revision_id / version_label / version_ref / published_at: The gated published revision.
    evaluated_at: When the verdict was computed.
    evaluated_signals: How many of the four took part. ``0`` means nothing could be judged and
        ``status`` is ``pass`` by the partial-inputs rule — branch on this, not on the status,
        if an unconfigured project must not read as a green light.
    counts: Signals per status.
    signals: The four, always all of them, in :data:`GATE_SIGNALS` order.
    policy: The thresholds this verdict was judged under.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `status` | string | yes | `pass` \| `warn` \| `fail`. |
| `summary` | string | yes | One line for a pipeline log. |
| `projectId` | string | yes | Project ID. |
| `projectSlug` | string or null | no | Project Slug. |
| `revisionId` | string | yes | Revision ID. |
| `versionLabel` | string or null | no | Version Label. |
| `versionRef` | string or null | no | `project/{slug}/{version}` — the reference the other CTG APIs address. |
| `publishedAt` | string (date-time) or null | no | Published At. |
| `evaluatedAt` | string (date-time) | yes | Evaluated At. |
| `evaluatedSignals` | integer | yes | How many signals took part in the verdict. |
| `counts` | map of integer | no | Counts. |
| `signals` | array of `GateSignal` | no | Signals. |
| `policy` | [`DeployGatePolicyOut`](#schema-deploygatepolicyout) | yes | Policy. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
