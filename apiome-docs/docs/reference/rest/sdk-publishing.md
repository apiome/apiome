---
title: "SDK publishing"
description: "REST endpoints tagged sdk-publishing: 6 operations."
sidebar_position: 59
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sdk-publishing` · 6 operations

## `POST /v1/projects/{tenant_slug}/{project_ref}/sdk-publish` {#publish-project-sdk-v1-projects-tenant-slug-project-ref-sdk-publish-post}

**Publish a version's SDK package to npm or PyPI (dry run by default)**

Builds the package a consumer would `npm install` / `pip install` from one **published** revision and, unless `dryRun` is false, uploads it with the tenant's stored registry credential.

**The version number is derived, not chosen.** It is `major.minor.<regen counter>`, where `major.minor` come from the revision's version line and the counter is how many releases that line's release series has already had. Re-publishing the same line bumps the patch; a new line starts a new series. A prerelease line stays a prerelease (`1.5.0-beta.2` on npm, `1.5.0b2` on PyPI). A line with no leading number cannot be mapped and is refused.

**A dry run is the same work minus the upload.** It resolves the credential (proving it is present and still decryptable), computes the version the next real publish would claim, builds the archive and reports its SHA-256 and contents. The build is byte-deterministic, so the digest a dry run reports is the digest a publish uploads.

**Provenance is embedded in the package's own metadata** — `package.json`'s `apiome` object, PyPI's `Project-URL` entries — naming the revision id, the version line, the release series and the generator, so an installed package traces back to its spec.

Requires `versions:publish`, for a dry run too. Audited as `sdk.package_publish`.

Operation id: `publish_project_sdk_v1_projects__tenant_slug___project_ref__sdk_publish_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for publish a version's sdk package to npm or pypi (dry run by default).

- `application/json` — [`SdkPublishRequest`](#schema-sdkpublishrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for publish a version's sdk package to npm or pypi (dry run by default). | `application/json` [`SdkPublishRunModel`](#schema-sdkpublishrunmodel) |
| 400 | Unsupported ecosystem, or the revision is not published. | — |
| 404 | Project or version not found in this tenant. | — |
| 409 | No free version number: another publish of this series is in flight. | — |
| 422 | No package name is configured, the version line cannot be mapped, no usable credential is stored, or there is nothing to package. | — |
| 503 | No credential-encryption key is configured on this deployment. | — |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-publish-runs` {#list-project-publish-runs-v1-projects-tenant-slug-project-ref-sdk-publish-runs-get}

**List a project's package publish history**

Every publish attempt, newest first — dry runs included, because a dry run is the record of what a release *would* have been.

Requires `versions:view`.

Operation id: `list_project_publish_runs_v1_projects__tenant_slug___project_ref__sdk_publish_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | query | string or null | no | Narrow to one ecosystem (`npm` or `pypi`). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's package publish history. | `application/json` [`SdkPublishRunListResponse`](#schema-sdkpublishrunlistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-publish-runs/{run_id}` {#get-project-publish-run-v1-projects-tenant-slug-project-ref-sdk-publish-runs-run-id-get}

**Read one publish run**

The run's outcome, the version it claimed and its event log. The log is stored redacted — a registry error quoting the credential it rejected is replaced before it is written.

Requires `versions:view`.

Operation id: `get_project_publish_run_v1_projects__tenant_slug___project_ref__sdk_publish_runs__run_id__get`

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
| 200 | Successful response for read one publish run. | `application/json` [`SdkPublishRunModel`](#schema-sdkpublishrunmodel) |
| 404 | Project or run not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-registry-credentials` {#list-project-registry-credentials-v1-projects-tenant-slug-project-ref-sdk-registry-credentials-get}

**List the credentials a project would publish with**

Both the workspace credentials and this project's overrides, workspace first, so a reader can see what is being overridden.

A credential is **write-only**: this API stores the token encrypted at rest and never returns it. What comes back is its public scheme prefix (`npm_`, `pypi-`), its length and a truncated SHA-256 — enough to confirm which token is stored, not enough to use it.

A **project** credential replaces the workspace one for that ecosystem. Unlike SDK-3.4's generation settings, credentials do not merge field by field: a token is atomic.

Ecosystems: `npm`, `pypi`. `gomod` is absent because a Go module is released by pushing a tag (SDK-4.2), not by uploading to a registry.

`registryUrl` defaults to the ecosystem's public registry and must be `https://` — a publish token sent over plain HTTP is a token disclosed.

Requires `projects:view`.

Operation id: `list_project_registry_credentials_v1_projects__tenant_slug___project_ref__sdk_registry_credentials_get`

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
| 200 | Successful response for list the credentials a project would publish with. | `application/json` [`RegistryCredentialListResponse`](#schema-registrycredentiallistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_ref}/sdk-registry-credentials/{ecosystem}` {#put-project-registry-credential-v1-projects-tenant-slug-project-ref-sdk-registry-credentials-ecosystem-put}

**Store this project's credential for one registry**

Replaces the workspace credential for this project and ecosystem, whole.

A credential is **write-only**: this API stores the token encrypted at rest and never returns it. What comes back is its public scheme prefix (`npm_`, `pypi-`), its length and a truncated SHA-256 — enough to confirm which token is stored, not enough to use it.

A **project** credential replaces the workspace one for that ecosystem. Unlike SDK-3.4's generation settings, credentials do not merge field by field: a token is atomic.

Ecosystems: `npm`, `pypi`. `gomod` is absent because a Go module is released by pushing a tag (SDK-4.2), not by uploading to a registry.

`registryUrl` defaults to the ecosystem's public registry and must be `https://` — a publish token sent over plain HTTP is a token disclosed.

Requires `projects:edit`. Audited as `governance.sdk_registry_credential.update`.

Operation id: `put_project_registry_credential_v1_projects__tenant_slug___project_ref__sdk_registry_credentials__ecosystem__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for store this project's credential for one registry.

- `application/json` — [`RegistryCredentialPutRequest`](#schema-registrycredentialputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for store this project's credential for one registry. | `application/json` [`RegistryCredentialOut`](#schema-registrycredentialout) |
| 404 | Project not found in this tenant. | — |
| 422 | The token, registry URL or ecosystem is not acceptable. | — |
| 503 | No credential-encryption key is configured on this deployment. | — |

## `DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-registry-credentials/{ecosystem}` {#delete-project-registry-credential-v1-projects-tenant-slug-project-ref-sdk-registry-credentials-ecosystem-delete}

**Remove this project's credential for one registry**

The project falls back to the workspace credential, if there is one.

Requires `projects:edit`. Audited as `governance.sdk_registry_credential.clear`.

Operation id: `delete_project_registry_credential_v1_projects__tenant_slug___project_ref__sdk_registry_credentials__ecosystem__delete`

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
| 200 | Successful response for remove this project's credential for one registry. | `application/json` object |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RegistryCredentialListResponse` {#schema-registrycredentiallistresponse}

The credentials configured for one scope.

Attributes:
    schema_version: The projection's shape.
    scope: The scope that was addressed.
    encryption_configured: Whether this deployment can store credentials at all.
    ecosystems: Which ecosystems can be published to.
    credentials: One entry per stored credential, tenant-wide first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `scope` | string | yes | Scope. |
| `encryptionConfigured` | boolean | yes | Encryption Configured. |
| `ecosystems` | array of string | yes | Ecosystems. |
| `credentials` | array of [`RegistryCredentialOut`](#schema-registrycredentialout) | yes | Credentials. |

### `RegistryCredentialOut` {#schema-registrycredentialout}

A stored credential, described without being revealed.

Attributes:
    schema_version: The projection's shape.
    ecosystem: ``npm`` or ``pypi``.
    scope: ``tenant`` or ``project``.
    project_id: The project this credential belongs to, when it is a project override.
    registry_url: Where it publishes.
    token_prefix: The public scheme prefix the token declares, when it declares one.
    token_length: How many characters the stored token has.
    token_fingerprint: A truncated SHA-256 of the token, for confirming a rotation.
    key_version: Which master key sealed it.
    readable: Whether the stored token can currently be decrypted. ``False`` means the key
        that sealed it is not configured — the credential is present but unusable, and saying
        so beats a publish failing with a decryption error.
    created_at: When it was first stored.
    updated_at: When it was last replaced.
    updated_by: Who last replaced it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `ecosystem` | string | yes | ``npm`` or ``pypi``. |
| `scope` | string | yes | ``tenant`` or ``project``. |
| `projectId` | string or null | no | Project ID. |
| `registryUrl` | string | yes | Registry URL. |
| `tokenPrefix` | string or null | no | Token Prefix. |
| `tokenLength` | integer or null | no | Token Length. |
| `tokenFingerprint` | string or null | no | Token Fingerprint. |
| `keyVersion` | integer or null | no | Key Version. |
| `readable` | boolean | no | Readable. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `RegistryCredentialPutRequest` {#schema-registrycredentialputrequest}

Body for storing a registry credential.

Attributes:
    token: The plaintext registry token. Sealed before it is written and never returned.
    registry_url: Where to publish; defaults to the ecosystem's public registry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | The registry token — an npm automation token or a PyPI API token. Stored envelope-encrypted; never returned by any route. |
| `registryUrl` | string or null | no | Registry endpoint. Defaults to `npm` → `https://registry.npmjs.org`, `pypi` → `https://upload.pypi.org/legacy/`. Must be `https://`. |

### `SdkPublishRequest` {#schema-sdkpublishrequest}

Body for a publish (or a dry run).

Attributes:
    ecosystem: ``npm`` or ``pypi``.
    version: The revision to publish — a revision UUID or a version label. Defaults to the
        project's latest revision.
    dry_run: When ``true`` (the default), everything is resolved and built and nothing is
        uploaded.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystem` | string | yes | `npm` or `pypi`. |
| `version` | string or null | no | Revision UUID or version label. Defaults to the latest revision. |
| `dryRun` | boolean | no | Validate without publishing. Defaults to **true**: uploading to a public registry is irreversible, so it is always the deliberate choice. |

### `SdkPublishRunListResponse` {#schema-sdkpublishrunlistresponse}

A page of publish history.

Attributes:
    runs: The rows, newest first.
    total: How many rows match.
    limit: The page size used.
    offset: The offset used.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`SdkPublishRunModel`](#schema-sdkpublishrunmodel) | yes | Runs. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `SdkPublishRunModel` {#schema-sdkpublishrunmodel}

One publish run.

Attributes:
    run_id: The ledger row.
    status: ``dry_run``, ``in_progress``, ``published``, ``already_published`` or ``failed``.
    dry_run: Whether anything was uploaded.
    ecosystem: ``npm`` or ``pypi``.
    package_name: The resolved package name.
    package_version: The version claimed.
    release_series: The series the counter was allocated under.
    regen_counter: Which release of that series this is.
    version_line: The version label the package version was derived from.
    registry_url: Where it published (or would have).
    credential_scope: Which scope supplied the credential.
    artifact_filename: The archive's filename.
    artifact_sha256: The archive's digest.
    artifact_bytes: The archive's size.
    operation_count: How many operations shipped snippets.
    truncated: Whether the API has more operations than one package carries snippets for.
    skipped: Operations no snippet is defined for.
    files: What is inside the archive (a dry run's report; empty for a stored run).
    provenance: The provenance embedded in the package's own metadata.
    log: The publish event log, redacted of secrets.
    error_code: Set when the run failed.
    error_message: Set when the run failed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string or null | no | Run ID. |
| `status` | string | yes | Status. |
| `dryRun` | boolean | yes | Dry Run. |
| `ecosystem` | string | yes | Ecosystem. |
| `packageName` | string | yes | Package Name. |
| `packageVersion` | string | yes | Package Version. |
| `releaseSeries` | string | yes | Release Series. |
| `regenCounter` | integer | yes | Regen Counter. |
| `versionLine` | string or null | no | Version Line. |
| `registryUrl` | string or null | no | Registry URL. |
| `credentialScope` | string or null | no | Credential Scope. |
| `artifactFilename` | string or null | no | Artifact Filename. |
| `artifactSha256` | string or null | no | Artifact Sha256. |
| `artifactBytes` | integer or null | no | Artifact Bytes. |
| `operationCount` | integer | no | Number of operation. |
| `truncated` | boolean | no | Truncated. |
| `skipped` | array of map of string | no | Skipped. |
| `files` | array of object | no | Files. |
| `provenance` | object | no | Provenance. |
| `log` | array of object | no | Log. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |
