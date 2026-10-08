---
title: "Tenant repositories"
description: "REST endpoints tagged tenant-repositories: 28 operations."
sidebar_position: 71
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `tenant-repositories` · 28 operations

## `GET /v1/tenants/{tenant_slug}/repositories` {#list-tenant-repositories-v1-tenants-tenant-slug-repositories-get}

**List Tenant Repositories**

List the tenant's registered repositories, each with its REPO-6.5 health badge.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    Every live repository for the tenant, newest registration first.

Operation id: `list_tenant_repositories_v1_tenants__tenant_slug__repositories_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list tenant repositories. | `application/json` [`TenantRepositoriesListResponse`](#schema-tenantrepositorieslistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/repositories` {#create-tenant-repository-v1-tenants-tenant-slug-repositories-post}

**Create Tenant Repository**

Operation id: `create_tenant_repository_v1_tenants__tenant_slug__repositories_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create tenant repository.

- `application/json` — [`TenantRepositoryCreate`](#schema-tenantrepositorycreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create tenant repository. | `application/json` [`TenantRepositoryCreateResponse`](#schema-tenantrepositorycreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}` {#get-tenant-repository-v1-tenants-tenant-slug-repositories-repository-id-get}

**Get Tenant Repository**

Read one registered repository, with its REPO-6.5 health badge.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to read.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The repository record.

Raises:
    HTTPException: 404 when the repository does not exist in this tenant.

Operation id: `get_tenant_repository_v1_tenants__tenant_slug__repositories__repository_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository. | `application/json` [`TenantRepositoryGetResponse`](#schema-tenantrepositorygetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/repositories/{repository_id}` {#update-tenant-repository-v1-tenants-tenant-slug-repositories-repository-id-patch}

**Update Tenant Repository**

Patch mutable repository settings (RAR-3.3 auto-refresh toggle, #3524).

Applies only the fields present in the request body. Currently the per-repo
``auto_refresh_enabled`` opt-out: when set to False the auto-refresh sweep skips
this repository (manual "Refresh Now" is unaffected). Returns the updated
repository record. 404 when the repository does not belong to the tenant.

Operation id: `update_tenant_repository_v1_tenants__tenant_slug__repositories__repository_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update tenant repository.

- `application/json` — [`TenantRepositoryUpdate`](#schema-tenantrepositoryupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update tenant repository. | `application/json` [`TenantRepositoryGetResponse`](#schema-tenantrepositorygetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/repositories/{repository_id}` {#delete-tenant-repository-v1-tenants-tenant-slug-repositories-repository-id-delete}

**Delete Tenant Repository**

Operation id: `delete_tenant_repository_v1_tenants__tenant_slug__repositories__repository_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete tenant repository. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/conflict-policy` {#get-repository-conflict-policy-v1-tenants-tenant-slug-repositories-repository-id-conflict-policy-get}

**Get Repository Conflict Policy**

Read a repository's refresh conflict policy and its per-file overrides (RAR-4.5, #3531).

When an auto-refresh finds the imported version has been hand-edited since
(RAR-4.4 divergence), this policy decides what happens: ``overwrite`` lets the
refresh win, ``hold-for-review`` (the default) parks it for a human, and
``new-branch`` lands the refresh on a side branch so neither side is lost. The
repository-wide setting applies to every file that has no override row.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to read.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The repository policy, the built-in default, the accepted tokens, and the
    per-file overrides.

Raises:
    HTTPException: 404 when the repository does not belong to the tenant.

Operation id: `get_repository_conflict_policy_v1_tenants__tenant_slug__repositories__repository_id__conflict_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get repository conflict policy. | `application/json` [`RepositoryConflictPolicyResponse`](#schema-repositoryconflictpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repositories/{repository_id}/conflict-policy` {#set-repository-conflict-policy-v1-tenants-tenant-slug-repositories-repository-id-conflict-policy-put}

**Set Repository Conflict Policy**

Set a repository's refresh conflict policy (RAR-4.5, #3531).

Applies to every file in the repository that has no per-file override. The
change takes effect on the next refresh tick; it never retroactively applies or
releases a refresh already held, and it never clears an existing override.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to configure.
    payload: The requested policy.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The repository's conflict-policy projection after the update.

Raises:
    HTTPException: 400 when the policy token is not recognised; 404 when the
        repository does not belong to the tenant.

Operation id: `set_repository_conflict_policy_v1_tenants__tenant_slug__repositories__repository_id__conflict_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set repository conflict policy.

- `application/json` — [`RepositoryConflictPolicyUpdate`](#schema-repositoryconflictpolicyupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set repository conflict policy. | `application/json` [`RepositoryConflictPolicyResponse`](#schema-repositoryconflictpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repositories/{repository_id}/conflict-policy/file` {#set-repository-file-conflict-policy-v1-tenants-tenant-slug-repositories-repository-id-conflict-policy-file-put}

**Set Repository File Conflict Policy**

Set or clear one file's conflict-policy override (RAR-4.5, #3531).

A ``policy`` value writes the override, so this one file deviates from the
repository-wide setting; ``policy: null`` removes the override and the file
inherits the repository policy again. Overrides are stored as exceptions, so
clearing one is a delete rather than a stored copy of the repository policy
that would go stale the moment the repository policy changed.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository the file belongs to.
    payload: The file (branch + path) and the policy to set, or null to clear.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The repository's conflict-policy projection after the change.

Raises:
    HTTPException: 400 when the policy token or the file key is invalid; 404
        when the repository does not belong to the tenant.

Operation id: `set_repository_file_conflict_policy_v1_tenants__tenant_slug__repositories__repository_id__conflict_policy_file_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set repository file conflict policy.

- `application/json` — [`RepositoryConflictPolicyOverrideRequest`](#schema-repositoryconflictpolicyoverriderequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set repository file conflict policy. | `application/json` [`RepositoryConflictPolicyResponse`](#schema-repositoryconflictpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/files` {#list-tenant-repository-files-v1-tenants-tenant-slug-repositories-repository-id-files-get}

**List Tenant Repository Files**

Operation id: `list_tenant_repository_files_v1_tenants__tenant_slug__repositories__repository_id__files_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `branch` | query | string or null | no | Git branch name. |
| `preset` | query | string or null | no | Query parameter: preset. |
| `glob` | query | string or null | no | Query parameter: glob. |
| `regex` | query | string or null | no | Query parameter: regex. |
| `hide_non_importable` | query | boolean | no | Query parameter: hide non importable. |
| `skip_vendor` | query | boolean | no | Query parameter: skip vendor. |
| `include_hidden` | query | boolean | no | Query parameter: include hidden. |
| `path_prefix` | query | string or null | no | Query parameter: path prefix. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list tenant repository files. | `application/json` [`TenantRepositoryFilesListResponse`](#schema-tenantrepositoryfileslistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/files/{file_id}/content` {#get-tenant-repository-file-content-v1-tenants-tenant-slug-repositories-repository-id-files-file-id-content-get}

**Get Tenant Repository File Content**

Stream file bytes from the source provider (GitHub) for one indexed ``tenant_repository_files`` row.

Operation id: `get_tenant_repository_file_content_v1_tenants__tenant_slug__repositories__repository_id__files__file_id__content_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `file_id` | path | string (uuid) | yes | Path parameter identifying the file id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository file content. | `application/json` [`TenantRepositoryFileContentResponse`](#schema-tenantrepositoryfilecontentresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/notification-preferences` {#get-tenant-repository-notification-preferences-v1-tenants-tenant-slug-repositories-repository-id-notification-preferences-get}

**Get Tenant Repository Notification Preferences**

Read this repository's scan/sync notification settings (REPO-7.2, #2800).

Reports every event type REPO-7.2 defines — not only the ones an operator has already
written a preference for — so this is the whole picture of what the repository will and
will not tell anyone about. Each entry also carries the throttle state for that event,
which is how "we have heard nothing" is distinguished from "we have been suppressing it".

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to read preferences for.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    One entry per event type, plus the throttle window being enforced.

Raises:
    HTTPException: 404 when the repository does not exist in this tenant.

Operation id: `get_tenant_repository_notification_preferences_v1_tenants__tenant_slug__repositories__repository_id__notification_preferences_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository notification preferences. | `application/json` [`RepositoryNotificationPreferencesResponse`](#schema-repositorynotificationpreferencesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repositories/{repository_id}/notification-preferences` {#set-tenant-repository-notification-preferences-v1-tenants-tenant-slug-repositories-repository-id-notification-preferences-put}

**Set Tenant Repository Notification Preferences**

Mute or restore this repository's scan/sync notifications (REPO-7.2, #2800).

A partial update: event types the request does not mention keep whatever state they
already had, so a client that renders fewer events than the server knows about cannot
silently reset the rest. Unknown event types and duplicates are rejected outright rather
than being ignored or resolved by write order — an opt-out that quietly did nothing is
the one failure an operator would not notice until the pager went off.

Changing a preference never touches the throttle: un-muting an event does not grant it a
fresh slot inside a window it has already used.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to update preferences for.
    payload: The preference changes to apply.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    Every event type's state after the update.

Raises:
    HTTPException: 400 when an event type is unknown or repeated; 404 when the
        repository does not exist in this tenant.

Operation id: `set_tenant_repository_notification_preferences_v1_tenants__tenant_slug__repositories__repository_id__notification_preferences_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set tenant repository notification preferences.

- `application/json` — [`RepositoryNotificationPreferencesUpdate`](#schema-repositorynotificationpreferencesupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set tenant repository notification preferences. | `application/json` [`RepositoryNotificationPreferencesResponse`](#schema-repositorynotificationpreferencesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/repositories/{repository_id}/refresh` {#refresh-tenant-repository-now-v1-tenants-tenant-slug-repositories-repository-id-refresh-post}

**Refresh Tenant Repository Now**

Trigger a one-shot manual "Refresh Now" (RAR-5.2, #3533).

Runs the same spec-faithful re-import path as the periodic sweep (RAR-4.1) for
a single file or the whole repository, on demand. It uses the stored import
spec (not defaults), honors the RAR-2.2 freshness gate (only files newer than
the last import enqueue) and the RAR-4.4 divergence guard (applied downstream
by the executor), and works even when scheduled auto-refresh is disabled —
the cadence and the ``auto_refresh_enabled`` / kill-switch gates are
deliberately bypassed.

Request body (all optional): ``path`` for a single file, ``branch`` to scope a
branch; omit both to refresh every branch that has a stored spec.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to refresh.
    payload: Optional ``path`` / ``branch`` selectors.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    Counts of jobs enqueued / skipped and the branches evaluated.

Raises:
    HTTPException: 404 when the repository does not belong to the tenant.

Operation id: `refresh_tenant_repository_now_v1_tenants__tenant_slug__repositories__repository_id__refresh_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for refresh tenant repository now.

- `application/json` — [`RepositoryRefreshNowRequest`](#schema-repositoryrefreshnowrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for refresh tenant repository now. | `application/json` [`RepositoryRefreshNowResponse`](#schema-repositoryrefreshnowresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/refresh-history` {#list-repository-refresh-history-v1-tenants-tenant-slug-repositories-repository-id-refresh-history-get}

**List Repository Refresh History**

List refresh-cycle audit history for a repository (RAR-5.3, #3534).

Each refresh cycle records who/what triggered it, the freshness decision, the
outcome (new-version / unchanged / diverged / failed), and the change-report and
version links. The history is queryable **per repo** (this endpoint) and **per
file** (add ``?path=``). Newest first.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository whose refresh history to list.
    path: Optional file path for per-file history.
    branch: Optional branch scope.
    trigger: Optional trigger filter.
    outcome: Optional outcome filter.
    since: Optional inclusive ISO-8601 lower bound on ``createdAt``.
    until: Optional inclusive ISO-8601 upper bound on ``createdAt``.
    limit: Page size (1..200).
    offset: Page offset.

Returns:
    A paginated, newest-first page of refresh-cycle entries.

Raises:
    HTTPException: 404 when the repository does not belong to the tenant.

Operation id: `list_repository_refresh_history_v1_tenants__tenant_slug__repositories__repository_id__refresh_history_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `path` | query | string or null | no | Restrict to a single imported file (per-file history). |
| `branch` | query | string or null | no | Restrict to a single branch. |
| `trigger` | query | string or null | no | Filter by trigger: scheduled \| manual \| webhook. |
| `outcome` | query | string or null | no | Filter by outcome: new-version \| unchanged \| diverged \| failed. |
| `since` | query | string or null | no | Inclusive lower bound on createdAt (ISO 8601). |
| `until` | query | string or null | no | Inclusive upper bound on createdAt (ISO 8601). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list repository refresh history. | `application/json` [`RefreshHistoryPageResponse`](#schema-refreshhistorypageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/repositories/{repository_id}/refresh/resume` {#resume-tenant-repository-refresh-v1-tenants-tenant-slug-repositories-repository-id-refresh-resume-post}

**Resume Tenant Repository Refresh**

Manually resume a repository whose auto-refresh was paused (RAR-3.4, #3525).

A repository auto-pauses after ``APIOME_REFRESH_AUTO_PAUSE_THRESHOLD``
consecutive refresh failures (extending REPO-4.5 to the refresh loop). This
clears the pause and resets the failure counter and backoff anchor, so the
repository is immediately eligible for the sweep again on its normal cadence.
Safe to call on a repository that is not paused (it just resets the failure
bookkeeping). Returns the updated repository record.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to resume.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The updated repository record (pause fields cleared).

Raises:
    HTTPException: 404 when the repository does not belong to the tenant.

Operation id: `resume_tenant_repository_refresh_v1_tenants__tenant_slug__repositories__repository_id__refresh_resume_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resume tenant repository refresh. | `application/json` [`TenantRepositoryGetResponse`](#schema-tenantrepositorygetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/webhook` {#get-tenant-repository-webhook-v1-tenants-tenant-slug-repositories-repository-id-webhook-get}

**Get Tenant Repository Webhook**

Report a repository's webhook subscription and its recent deliveries (REPO-4.3, #2781).

This is how an operator answers "is the hook actually firing, and is the provider holding
the secret I think it is". The **signing secret is never part of this response** — the
projection is built by :func:`repository_webhook_subscriptions.describe_subscription`
from an explicit field list, and the underlying read does not even select the ciphertext
column. What is returned is a truncated fingerprint of the secret, which confirms
identity without revealing it.

A repository registered before this feature — or one whose provisioning could not store a
subscription — reports ``subscription: null`` rather than an error: it simply has no
webhook, and still syncs on its polling cadence.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository to report on.
    limit: How many recent deliveries to include.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The subscription projection (or ``None``) plus the recent delivery ledger.

Raises:
    HTTPException: 404 when the repository does not belong to the tenant.

Operation id: `get_tenant_repository_webhook_v1_tenants__tenant_slug__repositories__repository_id__webhook_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `limit` | query | integer | no | Maximum recent deliveries to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository webhook. | `application/json` [`RepositoryWebhookStatusResponse`](#schema-repositorywebhookstatusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/repositories/{repository_id}/webhook/rotate` {#rotate-tenant-repository-webhook-secret-v1-tenants-tenant-slug-repositories-repository-id-webhook-rotate-post}

**Rotate Tenant Repository Webhook Secret**

Rotate a repository's webhook signing secret (REPO-4.7, #2785).

Mints a new secret, keeps the outgoing one verifying for a grace window (24h by default),
and updates the provider's hook to the new secret. The old secret expires on its own — the
background sweep retires it when the window closes, and keeps retrying the provider update
until then.

**No secret is returned**, new or old. There is nothing for an operator to copy: when the
provider hook is ours to edit we edit it, and when it is not (``providerSecretSynced``
false) the rotation is recorded with the reason so it can be repaired at the provider.
The response carries fingerprints and a deadline, which is what an operator actually needs
to answer "which secret is where, and how long do I have".

A rotation that reached the store is a success even when the provider could not be
updated: the new secret exists, the old one still works, and rolling the store back would
leave the tenant with an unchanged, aging secret and no record that anybody tried.
``providerSecretSynced`` is where that distinction lives, not the status code.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    repository_id: The repository whose subscription to rotate.
    payload: Optional grace-window override.
    auth_data: Authenticated principal; supplies the tenant scope and the audit actor.

Returns:
    The rotated subscription projection, the applied grace window, and whether the
    provider hook now holds the new secret.

Raises:
    HTTPException: 404 when the repository does not belong to the tenant or has no
        webhook subscription; 409 when the deployment cannot store a rotated secret
        (no encryption key, or a subscription that never held one); 500 when the store
        refused the write.

Operation id: `rotate_tenant_repository_webhook_secret_v1_tenants__tenant_slug__repositories__repository_id__webhook_rotate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string (uuid) | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for rotate tenant repository webhook secret.

- `application/json` — [`RepositoryWebhookRotateRequest`](#schema-repositorywebhookrotaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for rotate tenant repository webhook secret. | `application/json` [`RepositoryWebhookRotateResponse`](#schema-repositorywebhookrotateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-audit-export` {#export-tenant-repository-audit-v1-tenants-tenant-slug-repository-audit-export-get}

**Export Tenant Repository Audit**

Export the tenant's repository audit ledger for compliance (REPO-7.5, #2803).

Streams every ``repository.*`` row of ``apiome.workflow_audit`` in the requested
``created_at`` range, oldest first, as CSV or JSON — the structured, dateable
artifact a SOC 2 / ISO 27001 review asks for. Rows are read in keyset batches, so
an export far beyond 10k rows streams in constant memory. The response is served
as an attachment with a range-stamped filename.

Admin-only: requires a signed-in tenant administrator (API keys are rejected),
since the ledger spans every repository and actor in the workspace. The export
itself is appended to the same ledger as ``repository.audit_exported`` —
``success`` with the exact row count when the stream completes, ``failure`` with
the partial count when it aborts — so exports are evidence too, and appear in
the very next export.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    from_: Inclusive ISO 8601 lower bound; omit for "from the beginning".
    to: Inclusive ISO 8601 upper bound; omit for "up to now".
    export_format: ``csv`` or ``json`` (default ``json``).
    auth_data: Authenticated principal; must resolve to a tenant administrator.

Returns:
    The streamed export document.

Raises:
    HTTPException: 403 for non-administrators or API-key auth; 400 for an
        unknown format, a malformed bound, or an inverted range.

Operation id: `export_tenant_repository_audit_v1_tenants__tenant_slug__repository_audit_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `from` | query | string or null | no | Inclusive lower bound on the row's createdAt (ISO 8601). |
| `to` | query | string or null | no | Inclusive upper bound on the row's createdAt (ISO 8601). |
| `format` | query | string | no | Export format: csv or json (default json). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The export document, streamed. `format=json` yields one JSON object (`export` metadata envelope, `entries` array, trailing `rowCount`); `format=csv` yields a header line plus one row per entry with `detail` JSON-encoded in its cell. | `application/json` any; `text/csv` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-files` {#list-tenant-repository-spec-catalog-v1-tenants-tenant-slug-repository-files-get}

**List Tenant Repository Spec Catalog**

Tenant-wide catalog of every discovered spec across all repositories (REPO-6.4).

The per-repository Files listing answers "what is in this repo"; this answers "where does
this spec live" across the whole tenant. Search, filtering, ordering and pagination are all
evaluated in SQL so the response carries only the requested page.

Args:
    tenant_slug: Present for URL symmetry only — the tenant is always taken from the
        authenticated token, never from the path.
    auth_data: Injected auth context.
    q: Free-text search term.
    format: Format-family filter.
    repository_id: Single-repository filter.
    project_id: Filter to specs mapped or imported into one project.
    status: Derived-status filter.
    importable_only: Whether to hide indexed files that are not spec candidates.
    all_branches: Whether to list non-default branches.
    sort: Ordering key.
    limit: Page size (1..500).
    offset: Rows to skip.
    include_facets: Whether to compute filter options.

Returns:
    One page of catalog rows plus the total and matched counts.

Raises:
    HTTPException: 400 when a filter names an unknown format or status, or the search term
        is unusable.

Operation id: `list_tenant_repository_spec_catalog_v1_tenants__tenant_slug__repository_files_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `q` | query | string or null | no | Free-text search, matched as a case-insensitive substring against the file path, its detected kind, the repository full name and the mapped project name. |
| `format` | query | string or null | no | Format family key, or `all`. |
| `repository_id` | query | string (uuid) or null | no | Connected repository identifier. |
| `project_id` | query | string (uuid) or null | no | Project identifier that scopes the request. |
| `status` | query | string or null | no | Catalog status key, or `all`. |
| `importable_only` | query | boolean | no | Restrict to files classified as an importable spec type. |
| `all_branches` | query | boolean | no | List every tracked branch. Off by default so each spec appears once, on its repository's default branch. |
| `sort` | query | string or null | no | `repository` (default), `path`, `format`, `status`, `recent`. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `include_facets` | query | boolean | no | Also return the filter dropdown options. Request it once when the page mounts; paging and re-filtering do not need it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list tenant repository spec catalog. | `application/json` [`SpecCatalogResponse`](#schema-speccatalogresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-imports/{import_id}/spec` {#read-repository-import-spec-v1-tenants-tenant-slug-repository-imports-import-id-spec-get}

**Read Repository Import Spec**

Read the stored import spec for an imported repository file (RAR-1.5).

Two lookup modes share this route, mirroring the ticket's
``GET …/repository-imports/{id}/spec`` plus ``?path=`` variant:

- **By import id (default).** ``import_id`` is the
  ``apiome.repository_import_spec`` row id; the spec for that file lineage is
  returned. This is the "read the spec for a file/import id" path.
- **By path (``?path=`` present).** ``import_id`` is reinterpreted as the
  *repository* id and the latest spec for that repository / ``branch`` /
  ``path`` lineage is resolved. ``branch`` is optional: when omitted the most
  recently updated spec across branches for that path is returned.

In both modes the lookup is scoped to the caller's tenant (from the auth
token), so a spec belonging to another tenant returns 404 rather than
leaking. The returned ``options`` blob is upgraded on read to the current
envelope shape (RAR-1.4), and ``spec_schema_version`` reports that current
version.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    import_id: Import-spec row id, or repository id when ``path`` is given.
    auth_data: Authenticated principal; supplies the tenant scope.
    path: Repository-relative file path for the ``?path=`` lookup variant.
    branch: Optional branch filter for the ``?path=`` lookup variant.

Returns:
    The current-shape import spec for the resolved file.

Raises:
    HTTPException: 404 when no spec exists for the id/path within the tenant.

Operation id: `read_repository_import_spec_v1_tenants__tenant_slug__repository_imports__import_id__spec_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `import_id` | path | string (uuid) | yes | Path parameter identifying the import id segment. |
| `path` | query | string or null | no | Repository-relative file path. |
| `branch` | query | string or null | no | Git branch name. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read repository import spec. | `application/json` [`RepositoryImportSpecRead`](#schema-repositoryimportspecread) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-polling-quota` {#get-tenant-repository-polling-quota-v1-tenants-tenant-slug-repository-polling-quota-get}

**Get Tenant Repository Polling Quota**

Report this tenant's repository polling quota and window usage (REPO-4.6, #2784).

The quota bounds how many poll (refresh) jobs the auto-refresh scheduler may enqueue for
the tenant per rolling window, so one noisy tenant cannot starve the scheduler for
everyone else. This is the read an operator makes to answer "are we being deferred, and
how close to the ceiling are we?" — it reports the persisted bound, the bound actually
being enforced (which differs when quotas are disabled deployment-wide), and how much of
the current window is already spent.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The tenant's quota projection.

Operation id: `get_tenant_repository_polling_quota_v1_tenants__tenant_slug__repository_polling_quota_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository polling quota. | `application/json` [`RepositoryPollingQuotaResponse`](#schema-repositorypollingquotaresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repository-polling-quota` {#set-tenant-repository-polling-quota-v1-tenants-tenant-slug-repository-polling-quota-put}

**Set Tenant Repository Polling Quota**

Configure this tenant's repository polling quota (REPO-4.6, #2784).

Persists ``tenants.repository_polls_per_hour``, which the scheduler reads once per tick.
``0`` marks the tenant unlimited. The change takes effect on the next sweep tick; it does
not retroactively release repositories already deferred in the current one, and it never
touches any repository's failure bookkeeping.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    payload: The new quota.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The tenant's quota projection after the update.

Raises:
    HTTPException: 404 when the authenticated tenant no longer exists.

Operation id: `set_tenant_repository_polling_quota_v1_tenants__tenant_slug__repository_polling_quota_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set tenant repository polling quota.

- `application/json` — [`RepositoryPollingQuotaUpdate`](#schema-repositorypollingquotaupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set tenant repository polling quota. | `application/json` [`RepositoryPollingQuotaResponse`](#schema-repositorypollingquotaresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-quota-telemetry` {#get-tenant-repository-quota-telemetry-v1-tenants-tenant-slug-repository-quota-telemetry-get}

**Get Tenant Repository Quota Telemetry**

Report this tenant's quota and rate-limit telemetry (REPO-7.3, #2801).

The polling quota (REPO-4.6) and the scan budget (REPO-2.5) both work silently: without
this read, the only evidence a tenant is parked against its ceiling is a log line and a
per-replica counter that dies with the process. This returns the durable rolling-window
counters — polls and scan volume, with the quota's deferrals counted separately — plus
the tenant's current quota position, so a dashboard can render "where are we right now"
and "how did we get here" from one request.

Every metric is present in every response, zero-filled across the whole range, so a
tenant that has never been deferred renders a flat line rather than a missing panel. A
counter read that fails comes back with ``available: false`` and zeros rather than an
error, so the quota position is still answered.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    days: Trailing range in days; defaults to 7 and is capped at 90.
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The tenant's quota projection and its telemetry series.

Operation id: `get_tenant_repository_quota_telemetry_v1_tenants__tenant_slug__repository_quota_telemetry_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `days` | query | integer | no | Trailing range to report, in days. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant repository quota telemetry. | `application/json` [`RepositoryQuotaTelemetryResponse`](#schema-repositoryquotatelemetryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repository-webhook-ip-allowlist` {#get-repository-webhook-ip-allowlist-v1-tenants-tenant-slug-repository-webhook-ip-allowlist-get}

**Get Repository Webhook Ip Allowlist**

Show the webhook source-IP allowlist for this tenant (REPO-7.6, #2804).

The webhook endpoint carries no bearer token, so an IP filter in front of the HMAC check
is what stops every unsigned POST on the internet from reaching a real secret comparison.
This read answers the three questions the panel exists for: is the filter enforced for us,
what do the providers currently vouch for (and how stale is that list), and what have we
added ourselves.

Readable by any member who can view imports — the provider ranges are public information
and a tenant's own entries are its own — while every *change* below requires a tenant
administrator.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    auth_data: Authenticated principal; supplies the tenant scope.

Returns:
    The allowlist: deployment posture, cached provider ranges, and this tenant's entries.

Operation id: `get_repository_webhook_ip_allowlist_v1_tenants__tenant_slug__repository_webhook_ip_allowlist_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get repository webhook ip allowlist. | `application/json` [`RepositoryWebhookIpAllowlistResponse`](#schema-repositorywebhookipallowlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/repository-webhook-ip-allowlist/entries` {#add-repository-webhook-ip-allowlist-entry-v1-tenants-tenant-slug-repository-webhook-ip-allowlist-entries-post}

**Add Repository Webhook Ip Allowlist Entry**

Allow one additional source range for this tenant (REPO-7.6, #2804).

For the addresses no provider publishes: a self-hosted GitLab runner, a corporate egress
gateway, a delivery relay. The entry applies only to this tenant's repositories — a
workspace can widen its own filter and no one else's.

Tenant administrators only. Widening the range of addresses that may reach the signature
check is the same class of act as turning enforcement off, and the ticket puts that behind
the admin role.

A CIDR the tenant already has is updated (and re-enabled) rather than refused: a
re-submitted form should leave the operator with what they asked for, not a 409.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    payload: The CIDR to allow and why.
    auth_data: Authenticated principal; must resolve to a tenant administrator.

Returns:
    The allowlist, including the new entry.

Raises:
    HTTPException: 403 for non-administrators or API-key auth; 400 for a CIDR that is not
        a valid network or that carries host bits.

Operation id: `add_repository_webhook_ip_allowlist_entry_v1_tenants__tenant_slug__repository_webhook_ip_allowlist_entries_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add repository webhook ip allowlist entry.

- `application/json` — [`RepositoryWebhookIpAllowlistEntryCreate`](#schema-repositorywebhookipallowlistentrycreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for add repository webhook ip allowlist entry. | `application/json` [`RepositoryWebhookIpAllowlistResponse`](#schema-repositorywebhookipallowlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/repository-webhook-ip-allowlist/entries/{entry_id}` {#update-repository-webhook-ip-allowlist-entry-v1-tenants-tenant-slug-repository-webhook-ip-allowlist-entries-entry-id-patch}

**Update Repository Webhook Ip Allowlist Entry**

Enable or disable one allowlist entry (REPO-7.6, #2804).

Narrowing the filter during an incident should not cost the entry and its description —
an operator who deletes and later re-types a range loses the reason it was there.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    entry_id: The entry to toggle.
    payload: The new enabled state.
    auth_data: Authenticated principal; must resolve to a tenant administrator.

Returns:
    The allowlist, with the entry in its new state.

Raises:
    HTTPException: 403 for non-administrators or API-key auth; 404 when no entry of the
        tenant's has that id.

Operation id: `update_repository_webhook_ip_allowlist_entry_v1_tenants__tenant_slug__repository_webhook_ip_allowlist_entries__entry_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `entry_id` | path | string | yes | Path parameter identifying the entry id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update repository webhook ip allowlist entry.

- `application/json` — [`RepositoryWebhookIpAllowlistEntryUpdate`](#schema-repositorywebhookipallowlistentryupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update repository webhook ip allowlist entry. | `application/json` [`RepositoryWebhookIpAllowlistResponse`](#schema-repositorywebhookipallowlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/repository-webhook-ip-allowlist/entries/{entry_id}` {#delete-repository-webhook-ip-allowlist-entry-v1-tenants-tenant-slug-repository-webhook-ip-allowlist-entries-entry-id-delete}

**Delete Repository Webhook Ip Allowlist Entry**

Remove one allowlist entry (REPO-7.6, #2804).

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    entry_id: The entry to remove.
    auth_data: Authenticated principal; must resolve to a tenant administrator.

Returns:
    The allowlist without the entry.

Raises:
    HTTPException: 403 for non-administrators or API-key auth; 404 when no entry of the
        tenant's has that id.

Operation id: `delete_repository_webhook_ip_allowlist_entry_v1_tenants__tenant_slug__repository_webhook_ip_allowlist_entries__entry_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `entry_id` | path | string | yes | Path parameter identifying the entry id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete repository webhook ip allowlist entry. | `application/json` [`RepositoryWebhookIpAllowlistResponse`](#schema-repositorywebhookipallowlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repository-webhook-ip-allowlist/policy` {#set-repository-webhook-ip-policy-v1-tenants-tenant-slug-repository-webhook-ip-allowlist-policy-put}

**Set Repository Webhook Ip Policy**

Turn allowlist enforcement on or off for this tenant (REPO-7.6, #2804).

The bypass the ticket puts behind the tenant-administrator role. Disabling enforcement
means this tenant's repositories accept deliveries from any address — the posture that
existed before the filter — and it affects only this tenant.

A reason is required to disable and is recorded on both the policy row and the audit
ledger, because "who turned the filter off, when, and why" is the first thing a review
asks and the hardest thing to reconstruct afterwards.

Args:
    tenant_slug: Tenant slug from the path (scoping comes from the token).
    payload: The new enforcement state and, when disabling, why.
    auth_data: Authenticated principal; must resolve to a tenant administrator.

Returns:
    The allowlist with the new policy applied.

Raises:
    HTTPException: 403 for non-administrators or API-key auth; 400 when enforcement is
        being disabled with no reason given.

Operation id: `set_repository_webhook_ip_policy_v1_tenants__tenant_slug__repository_webhook_ip_allowlist_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set repository webhook ip policy.

- `application/json` — [`RepositoryWebhookIpPolicyUpdate`](#schema-repositorywebhookippolicyupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set repository webhook ip policy. | `application/json` [`RepositoryWebhookIpAllowlistResponse`](#schema-repositorywebhookipallowlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RefreshHistoryPageResponse` {#schema-refreshhistorypageresponse}

Stable JSON envelope for GET .../repositories/{id}/refresh-history (RAR-5.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | integer | no | Bumped only when item or pagination shape changes incompatibly. |
| `items` | array of `RefreshHistoryEntryOut` | yes | Items. |
| `pagination` | `RefreshHistoryPaginationOut` | yes | Pagination. |

### `RepositoryConflictPolicyOverrideRequest` {#schema-repositoryconflictpolicyoverriderequest}

Set or clear one file's conflict-policy override (RAR-4.5, #3531).

``policy`` set writes the override; ``policy`` null removes it so the file
inherits its repository's policy again.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `branch` | string | yes | The branch the file was imported from. |
| `path` | string | yes | Repository-relative path of the file. |
| `policy` | string or null | no | overwrite \| hold-for-review \| new-branch, or null to clear the override and inherit the repository policy. |

### `RepositoryConflictPolicyResponse` {#schema-repositoryconflictpolicyresponse}

Envelope returned by the conflict-policy read *and* by every mutation (RAR-4.5).

Mutations return the same projection the read does, so a settings panel
re-renders from the shape it loaded and can never drift from stored state.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `conflictPolicy` | `RepositoryConflictPolicyOut` | yes | Conflict Policy. |

### `RepositoryConflictPolicyUpdate` {#schema-repositoryconflictpolicyupdate}

Set a repository's conflict policy (RAR-4.5, #3531).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policy` | string | yes | overwrite \| hold-for-review \| new-branch. |

### `RepositoryImportSpecRead` {#schema-repositoryimportspecread}

Current-shape import spec returned by the read endpoint (RAR-1.5).

The response surface for ``GET …/repository-imports/{id}/spec`` (and its
``?path=`` lookup variant). It exposes the captured source descriptor and the
full ``SpecImportOptions`` payload, upgraded on read to the current envelope
shape, so the refresh worker, the UI status surface, and the CLI can replay
the user's original import request. ``spec_schema_version`` always reports the
current envelope version because ``options`` has already been migrated forward.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `spec_schema_version` | integer | no | Current envelope version the returned options conform to. |
| `source_kind` | string | yes | Importer discriminator (for example openapi-3, arazzo). |
| `format_override` | string or null | no | Explicit format override (the importer --format flag), when the user forced one. |
| `content_type` | string or null | no | MIME type used to read the file (for example application/yaml), when known. |
| `options` | `SpecImportOptions` | no | Full SpecImportOptions payload, upgraded to the current shape. |
| `last_imported_commit_sha` | string or null | no | Branch tip commit SHA observed for this file at import time (RAR-2.1). |
| `last_imported_committed_at` | string (date-time) or string or null | no | Committed-at timestamp of the file at import time. A later auto-refresh compares the remote committed_at against this anchor to gate newer-than re-imports (RAR-2.1/RAR-2.2). |
| `last_imported_blob_sha` | string or null | no | Blob SHA of the file content at import time (RAR-2.1). |
| `refresh_status` | `RefreshStatus` | no | Materialized per-file refresh state (RAR-2.3): one of up-to-date / stale / refreshing / failed / diverged. Derived from the current scan recency vs the last_imported_* anchors, overlaid with any in-flight refresh, last-attempt failure, or divergence hold. |
| `backfilled` | boolean | no | True when the spec was seeded by the RAR-1.6 backfill migration for an import that predates spec capture (RAR-1.2) — the options are system defaults and the source_kind was detected, not user-chosen. The UI can label such files 'imported before spec capture'. Cleared automatically when the lineage is genuinely re-imported. |

### `RepositoryNotificationPreferencesResponse` {#schema-repositorynotificationpreferencesresponse}

Envelope for a repository's notification preferences (REPO-7.2, #2800).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `repositoryId` | string | yes | The repository these preferences belong to. |
| `throttleWindowSeconds` | integer | yes | The quiet window applied per repository per event type. At most one notification is delivered per window (3600 = one per hour). |
| `preferences` | array of `RepositoryNotificationPreferenceOut` | yes | One entry per event type, in a stable order. |

### `RepositoryNotificationPreferencesUpdate` {#schema-repositorynotificationpreferencesupdate}

Set one or more of a repository's per-event opt-outs (REPO-7.2, #2800).

A partial update: event types absent from the request keep whatever state they already
had, so a client that knows about fewer events than the server cannot silently reset the
ones it does not render.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `preferences` | array of `RepositoryNotificationPreferenceUpdate` | yes | The preference changes to apply. At least one; duplicates of the same event type are rejected with 400 rather than resolved by write order. |

### `RepositoryPollingQuotaResponse` {#schema-repositorypollingquotaresponse}

Envelope for a tenant's polling-quota read or update (REPO-4.6, #2784).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `quota` | `RepositoryPollingQuotaOut` | yes | Quota. |

### `RepositoryPollingQuotaUpdate` {#schema-repositorypollingquotaupdate}

Set a tenant's repository polling quota (REPO-4.6, #2784).

``0`` is a meaningful value, not an unset one: it marks the tenant as unlimited. The upper
bound is a sanity rail — a five-figure quota is indistinguishable from unlimited in
practice, and asking for one is far more likely a typo than an intent.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pollsPerHour` | integer | yes | Maximum poll jobs this tenant may enqueue per rolling window. 0 = unlimited. Defaults are 60 for a standard tenant and 600 for the elevated/enterprise plan. |

### `RepositoryQuotaTelemetryResponse` {#schema-repositoryquotatelemetryresponse}

Envelope for the quota telemetry read (REPO-7.3, #2801).

Carries the current quota projection alongside the history so a caller can render
"42 of 600 used this hour" and "here is the last week" without a second request.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `quota` | `RepositoryPollingQuotaOut` | yes | Quota. |
| `telemetry` | `RepositoryQuotaTelemetryOut` | yes | Telemetry. |

### `RepositoryRefreshNowRequest` {#schema-repositoryrefreshnowrequest}

Dashboard: trigger a one-shot manual "Refresh Now" (RAR-5.2, #3533).

Both fields are optional and accept snake_case or camelCase so the UI can
send either:

- omit both → refresh the whole repository (every branch with a stored spec);
- ``branch`` only → refresh that branch;
- ``path`` (with or without ``branch``) → refresh that single file.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `path` | string or null | no | Path. |
| `branch` | string or null | no | Branch. |

### `RepositoryRefreshNowResponse` {#schema-repositoryrefreshnowresponse}

Result of a one-shot manual refresh (RAR-5.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `enqueued` | integer | yes | Enqueued. |
| `skipped` | integer | yes | Skipped. |
| `branches` | array of string | yes | Branches. |

### `RepositoryWebhookIpAllowlistEntryCreate` {#schema-repositorywebhookipallowlistentrycreate}

Add (or refresh) one additional allowlist entry (REPO-7.6, #2804).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `cidr` | string | yes | The range to allow. A bare address is accepted and stored as its single-host network; a value with host bits set (10.0.0.1/24) is rejected rather than silently widened. |
| `description` | string or null | no | Why this range should be allowed. Required in practice — an allowlist nobody can explain is one nobody dares prune. |

### `RepositoryWebhookIpAllowlistEntryUpdate` {#schema-repositorywebhookipallowlistentryupdate}

Enable or disable one existing allowlist entry (REPO-7.6, #2804).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | False stops the entry matching deliveries without deleting it. |

### `RepositoryWebhookIpAllowlistResponse` {#schema-repositorywebhookipallowlistresponse}

The webhook source-IP allowlist as a tenant administrator sees it (REPO-7.6, #2804).

Returned by the read *and* by every mutation, so a panel re-renders from the same shape it
loaded and can never drift from the stored state after an edit.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `enforcementEnabled` | boolean | yes | Deployment-wide switch. False means the filter is not enforced anywhere, whatever this tenant's own policy says. |
| `strict` | boolean | yes | True when a provider with no cached ranges blocks its deliveries instead of allowing them with a warning. |
| `refreshIntervalSeconds` | integer | yes | How often the provider ranges are refreshed. |
| `trustedProxyHops` | integer | yes | How many reverse proxies the deployment reads X-Forwarded-For through. 0 means the header is ignored and only the socket peer is trusted. |
| `tenantEnforcementEnabled` | boolean | yes | False is this tenant's bypass: its repositories accept deliveries from any address. Changing it requires the tenant-administrator role. |
| `bypassReason` | string or null | no | Why enforcement was turned off for this tenant. |
| `policyUpdatedAt` | string or null | no | When this tenant's policy was last changed (ISO 8601). |
| `providers` | array of `RepositoryIpProviderOut` | yes | Cached provider ranges, one entry per supported provider. |
| `entries` | array of `RepositoryIpAllowlistEntryOut` | yes | This tenant's additional ranges, oldest first. |

### `RepositoryWebhookIpPolicyUpdate` {#schema-repositorywebhookippolicyupdate}

Set this tenant's allowlist enforcement policy (REPO-7.6, #2804).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enforcementEnabled` | boolean | yes | False bypasses the allowlist for this tenant's repositories. Tenant administrators only. |
| `bypassReason` | string or null | no | Why enforcement is being turned off. Required when disabling; ignored when re-enabling. |

### `RepositoryWebhookRotateRequest` {#schema-repositorywebhookrotaterequest}

Ask for a repository's signing secret to be rotated (REPO-4.7, #2785).

The body carries at most a grace window, and even that is optional: rotating with the
deployment default is the case that should be one click. A requested window outside the
deployment's bounds is clamped rather than rejected — a rotation refused on a validation
technicality is a rotation that does not happen, which is the failure this ticket exists
to prevent.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `graceSeconds` | integer or null | no | How long the outgoing secret keeps verifying deliveries. Omit for the deployment default (24h). Clamped to the deployment's configured bounds. |

### `RepositoryWebhookRotateResponse` {#schema-repositorywebhookrotateresponse}

What a rotation did (REPO-4.7, #2785).

Carries no secret — new or old. The new secret exists only server-side and in the
provider's hook configuration; what a client gets is the fingerprint of each, which is
enough to tell the two apart and useless to anyone who intercepts it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `subscription` | `RepositoryWebhookSubscriptionOut` | yes | Subscription. |
| `graceSeconds` | integer | yes | The grace window actually applied, after clamping. |
| `providerSecretSynced` | boolean | yes | Whether the provider's hook was updated to the new secret. False means the grace window is load-bearing: the provider is still signing with the outgoing secret, and deliveries will start failing when the window closes unless the hook is updated (the background sweep keeps retrying until then). |
| `providerError` | string or null | no | Why the provider hook could not be updated, when it could not be. |

### `RepositoryWebhookStatusResponse` {#schema-repositorywebhookstatusresponse}

Webhook subscription + recent deliveries for one repository (REPO-4.3, #2781).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `subscription` | `RepositoryWebhookSubscriptionOut` or null | no | Subscription. |
| `events` | array of `RepositoryWebhookEventOut` | no | Events. |

### `SpecCatalogResponse` {#schema-speccatalogresponse}

A server-paginated page of the tenant-wide discovered-specs catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `catalog_total` | integer | yes | Specs in the catalog before any search or filter is applied. |
| `match_count` | integer | yes | Specs matching the current search and filters. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `sort` | string | yes | Sort. |
| `specs` | array of `SpecCatalogRow` | no | Specs. |
| `facets` | `SpecCatalogFacets` or null | no | Filter options; present only when the request set `include_facets=true`. |

### `TenantRepositoriesListResponse` {#schema-tenantrepositorieslistresponse}

TenantRepositoriesListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `repositories` | array of `TenantRepositoryRecord` | yes | Repositories. |

### `TenantRepositoryCreate` {#schema-tenantrepositorycreate}

Dashboard: register a Git repository under a tenant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source` | enum `"public_url"`, `"linked_account"` | yes | Provenance source for the record (for example human or imported). |
| `cloneUrl` | string or null | no | Clone URL. |
| `linkedAccountId` | string or null | no | Linked Account ID. |
| `repositoryFullName` | string or null | no | Repository Full Name. |

### `TenantRepositoryCreateResponse` {#schema-tenantrepositorycreateresponse}

TenantRepositoryCreateResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `repository` | `TenantRepositoryRecord` | yes | Repository. |

### `TenantRepositoryFileContentResponse` {#schema-tenantrepositoryfilecontentresponse}

On-demand file body for the repository file detail UI (GitHub-backed repos).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `path` | string | yes | Path. |
| `branch` | string | yes | Branch. |
| `display_kind` | string | yes | Display Kind. |
| `confidence` | string | no | Confidence. |
| `blob_sha` | string or null | no | Blob Sha. |
| `size_bytes` | integer or null | no | Size Bytes. |
| `content` | string | yes | Content. |
| `truncated` | boolean | no | Truncated. |

### `TenantRepositoryFilesListResponse` {#schema-tenantrepositoryfileslistresponse}

TenantRepositoryFilesListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `branch` | string | yes | Branch. |
| `branches` | array of string | yes | Branches. |
| `indexed_total` | integer | yes | Indexed Total. |
| `match_count` | integer | yes | Number of match. |
| `importable_match_count` | integer | yes | Number of importable match. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `files` | array of `TenantRepositoryFileRow` | yes | Files. |

### `TenantRepositoryGetResponse` {#schema-tenantrepositorygetresponse}

TenantRepositoryGetResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `repository` | `TenantRepositoryRecord` | yes | Repository. |

### `TenantRepositoryUpdate` {#schema-tenantrepositoryupdate}

Dashboard: patch mutable settings on a registered repository (RAR-3.3, RAR-4.5).

Only fields present in the request body are applied: the per-repo auto-refresh
toggle (``auto_refresh_enabled``, RAR-3.3) and the repository-wide conflict
policy (``refresh_conflict_policy``, RAR-4.5). Both accept the snake_case and
camelCase spellings so the UI can send either.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `autoRefreshEnabled` | boolean or null | no | Auto Refresh Enabled. |
| `refreshConflictPolicy` | string or null | no | Conflict policy for a diverged refresh: overwrite \| hold-for-review \| new-branch. Applies to every file in the repository that has no override. |
