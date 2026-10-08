---
title: "Schema test suites"
description: "REST endpoints tagged schema-test-suites: 11 operations."
sidebar_position: 55
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `schema-test-suites` · 11 operations

## `GET /v1/tenants/{tenant_slug}/schema-suites` {#list-schema-test-suites-v1-tenants-tenant-slug-schema-suites-get}

**List saved schema test suites**

Suites for the authenticated tenant, newest first, each carrying its newest run summary — including the ``regression`` flag the version and catalog detail surfaces badge on. ``ref`` narrows to the suites attached to one artifact (``{kind}/{artifact}`` — a version or type segment is tolerated and ignored).

Operation id: `list_schema_test_suites_v1_tenants__tenant_slug__schema_suites_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `ref` | query | string or null | no | Narrow to one artifact's suites. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list saved schema test suites. | `application/json` array of [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schema-suites` {#create-schema-test-suite-v1-tenants-tenant-slug-schema-suites-post}

**Create a saved schema test suite**

Persist a named set of payloads plus expected verdicts, attached to a stable schema reference (IXH-5.7). The reference survives revisions: either the stable form ``{kind}/{artifact}``, or a full IXH-5.1 reference whose version segment is discarded (``{kind}/{artifact}/{version}[/{type}]``). ``registry/…`` is rejected — registry types have no revisions to track a regression across. Payload expectations use the IXH-1.1 corpus vocabulary: a ``valid`` payload must validate, every other class must not.

Operation id: `create_schema_test_suite_v1_tenants__tenant_slug__schema_suites_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create a saved schema test suite.

- `application/json` — [`SchemaTestSuiteCreateRequest`](#schema-schematestsuitecreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a saved schema test suite. | `application/json` [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schema-suites/import` {#import-schema-test-suite-v1-tenants-tenant-slug-schema-suites-import-post}

**Import a suite from an IXH-1.1 corpus manifest**

Create a suite from a corpus manifest plus its payload files — the inverse of the export endpoint, and the same reading the CLI's ``--suite`` mode performs: entries carrying the ``instance-payload`` feature become payloads, expected verdicts derive from ``validity_class``, and non-payload entries are ignored.

Operation id: `import_schema_test_suite_v1_tenants__tenant_slug__schema_suites_import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import a suite from an ixh-1.1 corpus manifest.

- `application/json` — [`SuiteImportRequest`](#schema-suiteimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for import a suite from an ixh-1.1 corpus manifest. | `application/json` [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-suites/{suite_id}` {#get-schema-test-suite-v1-tenants-tenant-slug-schema-suites-suite-id-get}

**One suite with its payloads**

Read one suite in full.

Raises:
    HTTPException: 403 without ``types:view``, 404 when the suite is not visible.

Operation id: `get_schema_test_suite_v1_tenants__tenant_slug__schema_suites__suite_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for one suite with its payloads. | `application/json` [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/schema-suites/{suite_id}` {#update-schema-test-suite-v1-tenants-tenant-slug-schema-suites-suite-id-patch}

**Rename or re-describe a suite**

Apply a metadata patch (payload edits use the payloads route).

Raises:
    HTTPException: 403 without ``types:edit``, 404 when not visible, 409 for a
        duplicate name.

Operation id: `update_schema_test_suite_v1_tenants__tenant_slug__schema_suites__suite_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for rename or re-describe a suite.

- `application/json` — [`SchemaTestSuiteUpdateRequest`](#schema-schematestsuiteupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for rename or re-describe a suite. | `application/json` [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/schema-suites/{suite_id}` {#delete-schema-test-suite-v1-tenants-tenant-slug-schema-suites-suite-id-delete}

**Delete a suite and its history**

Delete a suite; payloads, runs and results follow.

Raises:
    HTTPException: 403 without ``types:delete``, 404 when the suite is not visible.

Operation id: `delete_schema_test_suite_v1_tenants__tenant_slug__schema_suites__suite_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a suite and its history. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-suites/{suite_id}/export` {#export-schema-test-suite-v1-tenants-tenant-slug-schema-suites-suite-id-export-get}

**Export a suite in the IXH-1.1 corpus manifest format**

The suite as a corpus manifest plus payload files. Materialize each ``files[*].content`` at its ``files[*].path`` next to a ``manifest.json`` holding ``manifest``, and the set runs in CI unchanged: ``apiome schema test --schema <ref> --suite manifest.json``.

Operation id: `export_schema_test_suite_v1_tenants__tenant_slug__schema_suites__suite_id__export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export a suite in the ixh-1.1 corpus manifest format. | `application/json` [`SuiteExportEnvelope`](#schema-suiteexportenvelope) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/schema-suites/{suite_id}/payloads` {#replace-schema-test-suite-payloads-v1-tenants-tenant-slug-schema-suites-suite-id-payloads-put}

**Replace a suite's payload set**

Replace-all semantics, bumping ``suite_version`` so every run can state which content version it executed. Partial edits are a client-side concern: read, modify, put back.

Operation id: `replace_schema_test_suite_payloads_v1_tenants__tenant_slug__schema_suites__suite_id__payloads_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace a suite's payload set.

- `application/json` — [`SuitePayloadsReplaceRequest`](#schema-suitepayloadsreplacerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace a suite's payload set. | `application/json` [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-suites/{suite_id}/runs` {#list-schema-test-suite-runs-v1-tenants-tenant-slug-schema-suites-suite-id-runs-get}

**A suite's run history**

Newest first. ``limit`` is clamped to 1..100.

Operation id: `list_schema_test_suite_runs_v1_tenants__tenant_slug__schema_suites__suite_id__runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for a suite's run history. | `application/json` array of [`SuiteRunSummaryModel`](#schema-suiterunsummarymodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schema-suites/{suite_id}/runs` {#run-schema-test-suite-v1-tenants-tenant-slug-schema-suites-suite-id-runs-post}

**Run a suite against a revision**

Execute every payload against the schema the suite is attached to, at the requested ``version`` (a label, a revision id, or ``latest``), judge each verdict against its expectation, and record the run. The reference is resolved once and pinned to the resolved revision, so a moving ``latest`` cannot split a run across revisions. Each verdict is diffed against the suite's previous completed run: a payload that passed there and failed here is flagged as a **regression**, on the result and on the run. An unresolvable reference records a run with ``status: error`` — that the suite could not run against a revision is history, not an exception.

Gated on ``types:view``, like the 5.1 validate endpoint this run repeats payload by payload: the run reads schemas and leaves bookkeeping about that read behind.

Operation id: `run_schema_test_suite_v1_tenants__tenant_slug__schema_suites__suite_id__runs_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for run a suite against a revision.

- `application/json` — [`SuiteRunRequest`](#schema-suiterunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for run a suite against a revision. | `application/json` [`SuiteRunDetailModel`](#schema-suiterundetailmodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-suites/{suite_id}/runs/{run_id}` {#get-schema-test-suite-run-v1-tenants-tenant-slug-schema-suites-suite-id-runs-run-id-get}

**One run with its per-payload results**

The full verdict record: per payload, the expectation, the tri-state validation outcome, the judged status, the previous run's status for the same payload, the regression flag, and the capped findings.

Operation id: `get_schema_test_suite_run_v1_tenants__tenant_slug__schema_suites__suite_id__runs__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suite_id` | path | string | yes | Path parameter identifying the suite id segment. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for one run with its per-payload results. | `application/json` [`SuiteRunDetailModel`](#schema-suiterundetailmodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SchemaTestSuiteCreateRequest` {#schema-schematestsuitecreaterequest}

A new suite: a name, a stable schema reference, and optional initial payloads.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Suite name, unique per tenant. |
| `description` | string or null | no | Optional description. |
| `ref` | string | yes | The schema reference the suite is attached to. Either the stable form ``{kind}/{artifact}[/latest/{type}]`` or a full IXH-5.1 reference ``{kind}/{artifact}/{version}[/{type}]`` — the version segment is discarded, because a suite outlives any one revision. ``registry/…`` is rejected: registry types have no revisions, so there is nothing to track a regression across. |
| `payloads` | array of `SuitePayloadModel` | no | Payloads. |

### `SchemaTestSuiteModel` {#schema-schematestsuitemodel}

A suite as every read returns it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `ref` | string | yes | The stable reference: ``{kind}/{artifact}[/{type}]``. |
| `ref_kind` | enum `"project"`, `"catalog"` | yes | Ref Kind. |
| `ref_artifact` | string | yes | Ref Artifact. |
| `ref_artifact_id` | string or null | no | Ref Artifact ID. |
| `ref_type` | string or null | no | Ref Type. |
| `suite_version` | integer | yes | Suite Version. |
| `payload_count` | integer | no | Number of payload. |
| `payloads` | array of `SuitePayloadModel` or null | no | Populated on detail reads; omitted from listings. |
| `latest_run` | [`SuiteRunSummaryModel`](#schema-suiterunsummarymodel) or null | no | The newest run, so listings can feed the regression badge. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or null | no | Last update timestamp (ISO 8601). |

### `SchemaTestSuiteUpdateRequest` {#schema-schematestsuiteupdaterequest}

A metadata patch: rename and/or re-describe. Payload edits use the payloads route.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `clear_description` | boolean | no | Set the description to null (distinct from omitting it). |

### `SuiteExportEnvelope` {#schema-suiteexportenvelope}

A suite in the IXH-1.1 corpus manifest format: the manifest plus the payload files.

Materialize ``files[*].content`` at ``files[*].path`` next to a ``manifest.json`` holding
``manifest`` and the set runs in CI unchanged: ``apiome schema test --schema <ref> --suite
manifest.json``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `suite` | [`SchemaTestSuiteModel`](#schema-schematestsuitemodel) | yes | Suite. |
| `manifest` | object | yes | An IXH-1.1 corpus manifest document. |
| `files` | array of `SuiteFileModel` | no | Files. |

### `SuiteImportRequest` {#schema-suiteimportrequest}

A suite to create from a corpus manifest plus its payload files.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Name for the created suite. |
| `description` | string or null | no | Free-text description. |
| `ref` | string | yes | The schema reference to attach the suite to (create-form grammar). |
| `manifest` | object | yes | An IXH-1.1 corpus manifest document. |
| `files` | array of `SuiteFileModel` | no | Files. |

### `SuitePayloadsReplaceRequest` {#schema-suitepayloadsreplacerequest}

The full replacement payload set; applying it bumps ``suite_version``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `payloads` | array of `SuitePayloadModel` | no | Payloads. |

### `SuiteRunDetailModel` {#schema-suiterundetailmodel}

A run with its per-payload results.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `suite_version` | integer | yes | Suite content version the run executed. |
| `requested_ref` | string | yes | The concrete reference the run was asked to target. |
| `resolved_revision_id` | string or null | no | The pinned revision; null when resolution failed. |
| `resolved_version_label` | string or null | no | Resolved Version Label. |
| `trigger` | enum `"manual"`, `"revision"` | yes | Trigger. |
| `status` | enum `"completed"`, `"error"` | yes | completed = every payload judged; error = the run could not execute. |
| `total` | integer | yes | Total. |
| `passed` | integer | yes | Passed. |
| `failed` | integer | yes | Failed. |
| `errored` | integer | yes | Errored. |
| `regression` | boolean | yes | True when any payload previously passed and now failed. |
| `baseline_run_id` | string or null | no | The prior completed run the verdict diff was computed against. |
| `message` | string or null | no | Message. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |
| `results` | array of `SuiteRunResultModel` | no | Results. |

### `SuiteRunRequest` {#schema-suiterunrequest}

What to run a suite against.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | no | A version label, a revision id, or ``latest``. |
| `trigger` | enum `"manual"`, `"revision"` | no | ``manual`` for a user-initiated run; ``revision`` when fired for a new revision. |
| `max_findings` | integer | no | Findings persisted per payload; 0 uses the server default (``APIOME_SCHEMA_SUITE_RESULT_FINDINGS_CAP``). |

### `SuiteRunSummaryModel` {#schema-suiterunsummarymodel}

One run of a suite, without its per-payload results.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `suite_version` | integer | yes | Suite content version the run executed. |
| `requested_ref` | string | yes | The concrete reference the run was asked to target. |
| `resolved_revision_id` | string or null | no | The pinned revision; null when resolution failed. |
| `resolved_version_label` | string or null | no | Resolved Version Label. |
| `trigger` | enum `"manual"`, `"revision"` | yes | Trigger. |
| `status` | enum `"completed"`, `"error"` | yes | completed = every payload judged; error = the run could not execute. |
| `total` | integer | yes | Total. |
| `passed` | integer | yes | Passed. |
| `failed` | integer | yes | Failed. |
| `errored` | integer | yes | Errored. |
| `regression` | boolean | yes | True when any payload previously passed and now failed. |
| `baseline_run_id` | string or null | no | The prior completed run the verdict diff was computed against. |
| `message` | string or null | no | Message. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |
