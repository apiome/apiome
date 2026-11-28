---
title: "Pacticipants"
description: "REST endpoints tagged pacticipants: 43 operations."
sidebar_position: 71
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.713.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pacticipants` · 43 operations

## `GET /v1/tenants/{tenant_slug}/pact-captures/links` {#list-capture-links-v1-tenants-tenant-slug-pact-captures-links-get}

**List mock capture URLs**

The workspace's private capture URLs, newest first, with `state` `live`, `revoked` or `expired`. The token is never shown again after creation; `token_prefix` identifies it.

Paged with `limit` (default 50, at most 200) and `cursor` (the previous page's `next_cursor`).

Requires `pacts:view`.

Operation id: `list_capture_links_v1_tenants__tenant_slug__pact_captures_links_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mock capture urls. | `application/json` [`CaptureLinkList`](#schema-capturelinklist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-captures/links` {#create-capture-link-v1-tenants-tenant-slug-pact-captures-links-post}

**Create a mock capture URL**

A private URL for clients that cannot add the `X-Mock-Capture` header: every call made under `{url}/<API path>` is served by the mock version and recorded for `consumer` at `consumer_version`. The token in it is shown **once**, in this response; only its digest is stored. The URL tags calls only — it does not open a private mock, which still needs its API key. It lasts `expires_in_days` (default 7, at most 30). Audited as `pacts.capture.link.create`.

Requires `pacts:create`.

Operation id: `create_capture_link_v1_tenants__tenant_slug__pact_captures_links_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create a mock capture url.

- `application/json` — [`CaptureLinkCreate`](#schema-capturelinkcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a mock capture url. | `application/json` [`CaptureLinkCreated`](#schema-capturelinkcreated) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pact-captures/links/{link_id}` {#revoke-capture-link-v1-tenants-tenant-slug-pact-captures-links-link-id-delete}

**Revoke a mock capture URL**

Stop recording through the URL. Calls made through it are still served; within 30 seconds (the mock's link cache) they are answered `X-Mock-Capture: not-recorded`. Revoking twice is harmless. Audited as `pacts.capture.link.revoke`.

Requires `pacts:edit`.

Operation id: `revoke_capture_link_v1_tenants__tenant_slug__pact_captures_links__link_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `link_id` | path | string | yes | Path parameter identifying the link id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for revoke a mock capture url. | `application/json` [`CaptureLink`](#schema-capturelink) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-captures/sessions` {#list-capture-sessions-v1-tenants-tenant-slug-pact-captures-sessions-get}

**List mock capture sessions**

The workspace's live capture sessions, newest activity first. A session holds the calls made to one mock version with `X-Mock-Capture: <consumer>@<version>`, or through a capture URL, for that consumer and version. Filter with `project`, `version` and `consumer` (exact). Expired sessions are never listed.

Paged with `limit` (default 50, at most 200) and `cursor` (the previous page's `next_cursor`).

Requires `pacts:view`.

Operation id: `list_capture_sessions_v1_tenants__tenant_slug__pact_captures_sessions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project` | query | string or null | no | Query parameter: project. |
| `version` | query | string or null | no | Endpoint or API version metadata. |
| `consumer` | query | string or null | no | Query parameter: consumer. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mock capture sessions. | `application/json` [`CaptureSessionList`](#schema-capturesessionlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-captures/sessions/{session_id}` {#read-capture-session-v1-tenants-tenant-slug-pact-captures-sessions-session-id-get}

**Read a mock capture session and its calls**

One session and a page of its calls in the order they were made. Each call has its method, path, the spec's path template (`null` when nothing in the spec matched), status, and `origin`: `spec`, `scenario`, `session` (stateful `X-Mock-Session` CRUD), `chaos` (an injected error), `forced` (`Prefer: code=`), `off-spec` or `rejected` (the mock refused the request). Request and response are stored after the mock's redaction rules; `redactions` says what was removed and why. An expired or unknown session is `404 capture-session-not-found`.

Paged with `limit` (default 50, at most 200) and `cursor` (the previous page's `next_cursor`).

Requires `pacts:view`.

Operation id: `read_capture_session_v1_tenants__tenant_slug__pact_captures_sessions__session_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `session_id` | path | string | yes | Path parameter identifying the session id segment. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a mock capture session and its calls. | `application/json` [`CaptureSessionDetail`](#schema-capturesessiondetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pact-captures/sessions/{session_id}` {#delete-capture-session-v1-tenants-tenant-slug-pact-captures-sessions-session-id-delete}

**Delete a mock capture session**

Delete the session and every call in it, so the next tagged call starts a new one. Audited as `pacts.capture.session.delete`.

Requires `pacts:delete`.

Operation id: `delete_capture_session_v1_tenants__tenant_slug__pact_captures_sessions__session_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `session_id` | path | string | yes | Path parameter identifying the session id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a mock capture session. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-captures/settings` {#read-capture-settings-v1-tenants-tenant-slug-pact-captures-settings-get}

**Read the mock capture settings**

How many days captures are kept (default 7), the fixed limits, and how many tagged calls were refused because the workspace already had the most live sessions it may. `can_edit` is `pacts:delete`.

Requires `pacts:view`.

Operation id: `read_capture_settings_v1_tenants__tenant_slug__pact_captures_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the mock capture settings. | `application/json` [`CaptureSettings`](#schema-capturesettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-captures/settings` {#save-capture-settings-v1-tenants-tenant-slug-pact-captures-settings-put}

**Save the mock capture retention**

Keep captures `retention_days` (1–30). The new value applies to calls recorded from now on; captures already stored keep the expiry they were written with. Audited as `pacts.capture.settings`.

Requires `pacts:delete`.

Operation id: `save_capture_settings_v1_tenants__tenant_slug__pact_captures_settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the mock capture retention.

- `application/json` — [`CaptureSettingsSave`](#schema-capturesettingssave)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the mock capture retention. | `application/json` [`CaptureSettings`](#schema-capturesettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-commit-statuses` {#get-pact-commit-statuses-v1-tenants-tenant-slug-pact-commit-statuses-get}

**List pact commit statuses**

The pact verdicts Apiome posted (or could not post) to GitHub and GitLab commits, most recently updated first. One status per pacticipant version and context (`apiome-pact/<consumer>/<provider>`): `pending` while a published pact awaits the provider's verification, then `pass` or `fail` on both the consumer's and the provider's commit.

`outcome` says what happened to the send: `dispatched` (the provider accepted it), `suppressed` (not attempted — `reason_code` says why: no repository URL, version not a commit SHA, repository not registered, unsupported provider, no stored credential, publishing switched off), `failed` (the provider refused or could not be reached) or `queued`.

Requires `pacts:view`.

Operation id: `get_pact_commit_statuses_v1_tenants__tenant_slug__pact_commit_statuses_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | query | string or null | no | Only this pacticipant's commits (handle). |
| `version` | query | string or null | no | Only this version number. |
| `outcome` | query | string or null | no | Only this outcome: queued, dispatched, suppressed, failed. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list pact commit statuses. | `application/json` [`CommitStatusList`](#schema-commitstatuslist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-commit-statuses/{status_id}/retry` {#retry-pact-commit-status-v1-tenants-tenant-slug-pact-commit-statuses-status-id-retry-post}

**Send a pact commit status again**

Send a `suppressed` or `failed` commit status again. Where it can go is decided afresh, so a retry after registering the repository, linking the account or fixing the pacticipant's repository URL sends it; one whose cause remains comes back with the same `reason_code`.

Requires `pacts:edit`.

Operation id: `retry_pact_commit_status_v1_tenants__tenant_slug__pact_commit_statuses__status_id__retry_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `status_id` | path | string | yes | Path parameter identifying the status id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for send a pact commit status again. | `application/json` [`CommitStatusRecord`](#schema-commitstatusrecord) |
| 404 | `pact-status-not-found`: no such status in this workspace. | — |
| 409 | `pact-status-not-retryable`: the status was accepted or is being sent. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-contract-settings` {#read-contract-settings-v1-tenants-tenant-slug-pact-contract-settings-get}

**Read the Contracts commit-status and agent switches**

The **CI and commit statuses** switches — a verdict on the consumer's commit, on the provider's commit, and whether bi-directional verdicts set statuses and fire webhooks — and the **Agents** switches: what an MCP-connected agent may do with contracts (read, draft, publish, record a deployment). `configured: false` shows the defaults. `can_edit` says whether the caller may change them (`pacts:delete`).

Requires `pacts:view`.

Operation id: `read_contract_settings_v1_tenants__tenant_slug__pact_contract_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the contracts commit-status and agent switches. | `application/json` [`ContractSettings`](#schema-contractsettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-contract-settings/agents` {#save-contract-agents-v1-tenants-tenant-slug-pact-contract-settings-agents-put}

**Save what MCP agents may do with contracts**

Replace the four agent switches. An MCP pact tool whose action is switched off is refused with `403 mcp-pact-agent-action-off` and the reason, and the refusal is audited (`pacts.agent.refused`). Whatever the switches say, an agent never records a deployment to an environment marked production. No agent tool drafts or publishes yet: those two switches apply when one ships.

Requires `pacts:delete`.

Operation id: `save_contract_agents_v1_tenants__tenant_slug__pact_contract_settings_agents_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save what mcp agents may do with contracts.

- `application/json` — [`AgentSettings`](#schema-agentsettings)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save what mcp agents may do with contracts. | `application/json` [`ContractSettings`](#schema-contractsettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-contract-settings/commit-statuses` {#save-contract-commit-statuses-v1-tenants-tenant-slug-pact-contract-settings-commit-statuses-put}

**Save the commit-status switches**

Replace the three switches. A status a switch keeps from being written is still recorded, as `suppressed` with reason `pact-status-switched-off`, in `GET …/pact-commit-statuses`. Turning on `bidirectional` makes each new bi-directional verdict set its statuses and fire its `provider_verification_*` webhooks.

Requires `pacts:delete`.

Operation id: `save_contract_commit_statuses_v1_tenants__tenant_slug__pact_contract_settings_commit_statuses_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the commit-status switches.

- `application/json` — [`CommitStatusSettings`](#schema-commitstatussettings)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the commit-status switches. | `application/json` [`ContractSettings`](#schema-contractsettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-retention` {#run-pact-retention-v1-tenants-tenant-slug-pact-retention-post}

**Clean up pacticipant versions (dry run first)**

Delete the versions no keep selector needs. A version is **kept** when any of these holds:

- it is its pacticipant's latest version (always);
- `keep.latest_per_branch`: it is one of the newest N versions of a branch;
- `keep.deployed_or_released` (default `true`): it is currently deployed or released;
- `keep.created_within_days`: it was recorded in the last D days.

Every other live version of the pacticipants named in `pacticipants` (all of them when omitted) is deleted — softly, with its pacts, results and deployments, restorable until it is purged (`grace_days`).

**Dry run first.** `dry_run` defaults to `true`: the answer is the plan and its `plan_digest`, and nothing changes. To apply, send the same request with `dry_run: false` and that `plan_digest`. If the plan changed in between, the answer is `409 pact-retention-plan-changed` with the fresh plan under `detail.plan`.

A run deletes at most `max_deletions` versions, oldest first; `remaining` counts the rest for the next run.

A dry run requires `pacts:view`; applying requires `pacts:delete`.

Operation id: `run_pact_retention_v1_tenants__tenant_slug__pact_retention_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for clean up pacticipant versions (dry run first).

- `application/json` — [`RetentionRequest`](#schema-retentionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for clean up pacticipant versions (dry run first). | `application/json` [`RetentionPlan`](#schema-retentionplan) |
| 409 | `pact-retention-plan-changed`: review `detail.plan` and apply its digest. | — |
| 422 | No keep selector, no `plan_digest` when applying, or a run too large. | — |

## `GET /v1/tenants/{tenant_slug}/pact-retention/deleted` {#list-pact-retention-deleted-v1-tenants-tenant-slug-pact-retention-deleted-get}

**List recently deleted pacticipants and versions**

Deleted pacticipants, and versions deleted on their own (by hand or by the clean-up), newest first, each with who deleted it, what comes back with a restore and `purge_after` — when it is removed for good under the workspace's restore window. Restore one with `POST …/pacticipants/{pacticipant}/restore` or `POST …/pacticipants/{pacticipant}/versions/{number}/restore`.

Requires `pacts:view`; `can_restore` says whether the caller may restore (`pacts:delete`).

Operation id: `list_pact_retention_deleted_v1_tenants__tenant_slug__pact_retention_deleted_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Rows per page. |
| `cursor` | query | string | no | `next_cursor` of the previous page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list recently deleted pacticipants and versions. | `application/json` [`DeletedPage`](#schema-deletedpage) |
| 422 | `pact-retention-bad-cursor`. | — |

## `GET /v1/tenants/{tenant_slug}/pact-retention/policy` {#read-pact-retention-policy-v1-tenants-tenant-slug-pact-retention-policy-get}

**Read the workspace's clean-up rules**

The Contracts clean-up rules: what is kept (every deployed or released version, always; the latest N of each main branch; the latest N of every other branch, optionally for D days; versions with a listed tag), whether the clean-up runs nightly (after 02:00 UTC), and how many days a deleted item stays restorable. `configured: false` shows the defaults (clean-up off). `last_run` / `next_run_at` say what the nightly run did and when it runs next; `can_edit` whether the caller may change the rules.

Requires `pacts:view`.

Operation id: `read_pact_retention_policy_v1_tenants__tenant_slug__pact_retention_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the workspace's clean-up rules. | `application/json` [`RetentionPolicy`](#schema-retentionpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-retention/policy` {#save-pact-retention-policy-v1-tenants-tenant-slug-pact-retention-policy-put}

**Save the workspace's clean-up rules**

Replace the clean-up rules; a field left out takes its default. Every version deployed or released anywhere is always kept: `keep_deployed_or_released: false` is refused with `422 pact-retention-keeps-in-use` (*Deployed and released versions are always kept.*). An unknown field, a repeated tag or `keep_other_branch_days` without `keep_other_branch_latest` is refused with the reason — nothing is dropped silently.

Run `POST …/pact-retention/policy/preview` first to see what the rules remove. Requires `pacts:delete` (Owner and Admin).

Operation id: `save_pact_retention_policy_v1_tenants__tenant_slug__pact_retention_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the workspace's clean-up rules.

- `application/json` — [`RetentionRules`](#schema-retentionrules)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the workspace's clean-up rules. | `application/json` [`RetentionPolicy`](#schema-retentionpolicy) |
| 422 | `pact-retention-keeps-in-use`, or an invalid rule. | — |

## `POST /v1/tenants/{tenant_slug}/pact-retention/policy/preview` {#preview-pact-retention-policy-v1-tenants-tenant-slug-pact-retention-policy-preview-post}

**Preview what the clean-up rules remove**

What the saved rules — or the draft in `rules` — would remove if the clean-up ran now: the versions, with the pacts and verification results that go with them, listed per pacticipant. It is planned exactly as the nightly run plans, so it is what the next run removes unless something is published, deployed or deleted in between. Nothing changes.

`nightly_enabled: false` means nothing is removed while clean-up is off.

Requires `pacts:view`.

Operation id: `preview_pact_retention_policy_v1_tenants__tenant_slug__pact_retention_policy_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview what the clean-up rules remove.

- `application/json` — [`RetentionPreviewRequest`](#schema-retentionpreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview what the clean-up rules remove. | `application/json` [`RetentionPreview`](#schema-retentionpreview) |
| 422 | `pact-retention-keeps-in-use`, `pact-retention-too-many-versions`, or an invalid rule. | — |

## `GET /v1/tenants/{tenant_slug}/pact-setup` {#read-pact-setup-v1-tenants-tenant-slug-pact-setup-get}

**Read the Contracts guided set-up**

The six sections of the set-up — who talks to whom, where things run, pipelines, the first pact, the provider's side, gates — each `done`, `next` or `todo`. A section is done when what it sets up exists, whoever made it, or (pipelines, provider's side, gates) when a Contracts admin marked it; a workspace with a completed broker migration has the first two done. Also: the pacticipants proposed from projects (providers) and from registered repositories no project is read from (consumers), each with its main branch, owner team and the pacticipant that already exists for it; and the registered GitHub repositories with whether a linked account can write to them. Counts that could grow without bound stop at 100.

Requires `pacts:view`. `can_edit` is `pacts:delete`.

Operation id: `read_pact_setup_v1_tenants__tenant_slug__pact_setup_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the contracts guided set-up. | `application/json` [`PactSetupState`](#schema-pactsetupstate) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-setup` {#save-pact-setup-v1-tenants-tenant-slug-pact-setup-put}

**Save progress of the Contracts guided set-up**

Change only what is sent: `mark` sets or clears a section's by-hand mark, `first_pact_path` records the chosen way to the first pact, `ci_key` records the API key just created for CI (its id and prefix, never its secret) so a resume does not create a second one, and `forget_ci_key` clears it without revoking the key. Audited as `pacts.setup.update`.

Requires `pacts:delete`.

Operation id: `save_pact_setup_v1_tenants__tenant_slug__pact_setup_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save progress of the contracts guided set-up.

- `application/json` — [`PactSetupSave`](#schema-pactsetupsave)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save progress of the contracts guided set-up. | `application/json` [`PactSetupState`](#schema-pactsetupstate) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-setup/github/pull-requests` {#open-pact-setup-pull-requests-v1-tenants-tenant-slug-pact-setup-github-pull-requests-post}

**Open pull requests adding can-i-deploy and record-deployment**

For each registered repository, open a pull request from the branch `apiome/contracts-setup` adding `.github/workflows/apiome-contracts.yml`: can-i-deploy for the given pacticipant and environment on every pull request and push, and record-deployment after a push to the default branch. Each repository answers `opened`, `exists` (a pull request from the set-up is already open; its branch is brought up to date), or `skipped` with the reason (the same file is already on the default branch, no linked account, a branch rule) — and always the workflow's text, so it can be added by hand. With `preview: true` GitHub is not called and every repository answers `preview`. Audited as `pacts.setup.github.pull_requests` (a preview is not).

Requires `pacts:delete`.

Operation id: `open_pact_setup_pull_requests_v1_tenants__tenant_slug__pact_setup_github_pull_requests_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open pull requests adding can-i-deploy and record-deployment.

- `application/json` — [`PactSetupPullRequestsRequest`](#schema-pactsetuppullrequestsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for open pull requests adding can-i-deploy and record-deployment. | `application/json` [`PactSetupPullRequestsResponse`](#schema-pactsetuppullrequestsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-setup/github/secrets` {#write-pact-setup-secrets-v1-tenants-tenant-slug-pact-setup-github-secrets-post}

**Write the broker address and key into repositories as Actions secrets**

Write `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN` as GitHub Actions secrets into each registered repository, with the GitHub account the repository was registered with. The token is sealed to the repository's key and sent on; it is never stored, logged or audited. Each repository answers `written`, or `skipped` with the reason (not this workspace's, not github.com, no linked account, the account may not manage secrets): nothing fails as a whole. Writing again replaces the values. Audited as `pacts.setup.github.secrets`.

Requires `pacts:delete`.

Operation id: `write_pact_setup_secrets_v1_tenants__tenant_slug__pact_setup_github_secrets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for write the broker address and key into repositories as actions secrets.

- `application/json` — [`PactSetupSecretsRequest`](#schema-pactsetupsecretsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for write the broker address and key into repositories as actions secrets. | `application/json` [`PactSetupSecretsResponse`](#schema-pactsetupsecretsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipant-labels` {#list-workspace-labels-v1-tenants-tenant-slug-pacticipant-labels-get}

**List the workspace's labels**

Every distinct label on the workspace's pacticipants, by name. `GET …/pacticipants?label=…` lists the pacticipants carrying one.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_workspace_labels_v1_tenants__tenant_slug__pacticipant_labels_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the workspace's labels. | `application/json` [`LabelNameListResponse`](#schema-labelnamelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants` {#list-tenant-pacticipants-v1-tenants-tenant-slug-pacticipants-get}

**List pacticipants**

The applications registered as pacticipants in this workspace, ordered by handle. `label` keeps the ones carrying that label. `state=deleted` lists the deleted ones instead, each with `deleted_at` and `purge_after` (when it is removed for good unless restored).

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_tenant_pacticipants_v1_tenants__tenant_slug__pacticipants_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `label` | query | string or null | no | Only pacticipants with this label. |
| `state` | query | string | no | `live` (the default) or `deleted`: what was deleted and is waiting to be purged. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list pacticipants. | `application/json` [`PacticipantListResponse`](#schema-pacticipantlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pacticipants` {#register-pacticipant-v1-tenants-tenant-slug-pacticipants-post}

**Register a pacticipant**

Register an application that takes part in pacts. The handle (`slug`) is what URLs and CI name; it is derived from `name` when omitted (`Billing Service` becomes `billing-service`), is unique in the workspace, and is **not** editable afterwards.

`project` binds a provider to the project that describes it; `consumer_id` binds a consumer to its row in the consumer registry. Both are optional and must belong to this workspace. Deleting the project or the consumer clears the binding and keeps the pacticipant.

Requires `pacts:create`.

Operation id: `register_pacticipant_v1_tenants__tenant_slug__pacticipants_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a pacticipant.

- `application/json` — [`PacticipantInput`](#schema-pacticipantinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 409 | `pacticipant-slug-taken`: the workspace already has that handle. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#read-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-get}

**Read one pacticipant**

Read a pacticipant by its handle, its id, or its display name (`Billing Service` finds `billing-service`).

Requires `pacts:view`.

Operation id: `read_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#patch-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-patch}

**Update a pacticipant**

Rename it, or change the display name, repository URL, main branch or bindings. A field that is left out is not changed; `null` clears `display_name`, `repository_url` and `main_branch` and unbinds `project` and `consumer_id`.

A new `name` renames the pacticipant: the handle and the whole history stay, and the old name and the new one both keep resolving to it (as `{pacticipant_ref}` and in a published pact), listed in `aliases`. `409 pacticipant-slug-taken` when another pacticipant has, or had, that name. The handle cannot be changed.

Requires `pacts:edit`.

Operation id: `patch_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update a pacticipant.

- `application/json` — [`PacticipantPatch`](#schema-pacticipantpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update a pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 409 | `pacticipant-slug-taken`: another pacticipant answers to that name. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}` {#remove-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-delete}

**Delete a pacticipant**

Delete a pacticipant **with all of its versions** — and with them its pacts, verification results, deployments, branches and tags. The delete is soft: everything disappears from every read at once, `POST …/restore` brings it back for `APIOME_PACT_DELETION_GRACE_DAYS` (default 30) days, and it is then purged for good. The handle is free again at once. The project and the consumer it was bound to are not touched.

A pacticipant with a version that is currently deployed or released is refused (`409 pacticipant-version-in-use`) unless `force=true`. `reason` is stored with the delete and in the audit trail.

Requires `pacts:delete` (the built-in Owner and Admin roles).

Operation id: `remove_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `reason` | query | string or null | no | Why; stored with the delete and audited. |
| `force` | query | boolean | no | Delete even when a version is currently deployed or released. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a pacticipant. | — |
| 409 | `pacticipant-version-in-use`: a version is deployed or released. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/branches` {#list-pacticipant-branches-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-branches-get}

**List a pacticipant's branches**

The branches versions were recorded on, by name, each with its head: the latest version recorded on it. `is_main` marks the pacticipant's main branch.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_pacticipant_branches_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__branches_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a pacticipant's branches. | `application/json` [`PacticipantBranchListResponse`](#schema-pacticipantbranchlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/contract-sources` {#read-contract-sources-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-contract-sources-get}

**Read a provider's standing contract sources**

Where this provider's contract is published from automatically.

- `onProjectPublish` — each time a version of the project the pacticipant is bound to is published, it is rendered (OpenAPI 3.1, as `apiomeVersion` renders it) and published as the contract of provider version `<version label>` on the pacticipant's main branch. Drafts are never published.
- `repository` — on every push to `branch` of a registered repository (`repositoryId`), the file at `path` is published with the pushed commit as the provider version. The repository needs a push webhook.

Each automatic publish is compared with the pacts that need it, as a publish is, and audited as `pacts.contract.auto_publish` with its outcome and reason. A provider version's contract is write-once, so a repeated trigger records nothing new. Turning a source off stops new publishes only.

`warnings` names each source that will not fire right now. Requires `pacts:view`.

Operation id: `read_contract_sources_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__contract_sources_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a provider's standing contract sources. | `application/json` [`ContractSourcesRecord`](#schema-contractsourcesrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/contract-sources` {#put-contract-sources-route-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-contract-sources-put}

**Set a provider's standing contract sources**

Replace where this provider's contract is published from automatically; both off removes the setting.

- `onProjectPublish` — each time a version of the project the pacticipant is bound to is published, it is rendered (OpenAPI 3.1, as `apiomeVersion` renders it) and published as the contract of provider version `<version label>` on the pacticipant's main branch. Drafts are never published.
- `repository` — on every push to `branch` of a registered repository (`repositoryId`), the file at `path` is published with the pushed commit as the provider version. The repository needs a push webhook.

Each automatic publish is compared with the pacts that need it, as a publish is, and audited as `pacts.contract.auto_publish` with its outcome and reason. A provider version's contract is write-once, so a repeated trigger records nothing new. Turning a source off stops new publishes only.

Refused with a reason, never ignored: `409 contract-source-no-project` for `onProjectPublish` on a pacticipant bound to no project, `404 contract-source-repository-not-found` for a repository of another workspace, `422 contract-source-repository-unsupported` for a repository whose files cannot be read on a push (only GitHub's can), `400 contract-source-invalid-path` for a path that is not a repository-relative `.yaml` / `.yml` / `.json` file.

Requires `pacts:edit`, and `imports:view` with `repository`.

Operation id: `put_contract_sources_route_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__contract_sources_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set a provider's standing contract sources.

- `application/json` — [`ContractSourcesInput`](#schema-contractsourcesinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set a provider's standing contract sources. | `application/json` [`ContractSourcesRecord`](#schema-contractsourcesrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/deletion-impact` {#read-pacticipant-deletion-impact-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-deletion-impact-get}

**What deleting a pacticipant takes with it**

Read, before deleting, what `DELETE …/pacticipants/{ref}` would take with it: its live versions, the pacts that name it as consumer or provider and their verification results, the providers that lose it as a consumer (their can-i-deploy answers change) and the consumers that lose it as a provider (at most 20 names each, with totals), and how many days the delete can be undone. `blocked` is true while a version is deployed or released (`in_use` names them): the delete is refused until the undeployment is recorded.

Requires `pacts:view`.

Operation id: `read_pacticipant_deletion_impact_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__deletion_impact_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for what deleting a pacticipant takes with it. | `application/json` [`DeletionImpact`](#schema-deletionimpact) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/labels` {#list-labels-of-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-labels-get}

**List a pacticipant's labels**

The labels on this pacticipant, by name.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_labels_of_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__labels_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a pacticipant's labels. | `application/json` [`PacticipantLabelListResponse`](#schema-pacticipantlabellistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label}` {#read-pacticipant-label-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-labels-label-get}

**Read a label**

One label of a pacticipant; 404 when it does not carry it.

Requires `pacts:view`.

Operation id: `read_pacticipant_label_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__labels__label__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a label. | `application/json` [`PacticipantLabelRecord`](#schema-pacticipantlabelrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label}` {#put-pacticipant-label-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-labels-label-put}

**Label a pacticipant**

Put a label on a pacticipant (`team-billing`, `tier-1`). Answers `201` when the label is new and `200` when the pacticipant already had it. A label may contain `/`.

Requires `pacts:edit`.

Operation id: `put_pacticipant_label_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__labels__label__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for label a pacticipant. | `application/json` [`PacticipantLabelRecord`](#schema-pacticipantlabelrecord) |
| 201 | The label was added by this request. | `application/json` [`PacticipantLabelRecord`](#schema-pacticipantlabelrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label}` {#delete-pacticipant-label-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-labels-label-delete}

**Remove a label**

Take a label off a pacticipant; 404 when it does not carry it.

Requires `pacts:edit`.

Operation id: `delete_pacticipant_label_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__labels__label__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for remove a label. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/restore` {#restore-deleted-pacticipant-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-restore-post}

**Restore a deleted pacticipant**

Undo a pacticipant's delete before it is purged, with the versions that were deleted along with it (a version deleted on its own before stays deleted). `{pacticipant_ref}` is the deleted pacticipant's id, handle or name; with several deleted ones of the same handle the most recently deleted comes back — pass the id (from `?state=deleted`) to choose.

`409 pacticipant-restore-conflict` when a live pacticipant has taken the handle since.

Requires `pacts:delete`.

Operation id: `restore_deleted_pacticipant_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__restore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for restore a deleted pacticipant. | `application/json` [`PacticipantRecord`](#schema-pacticipantrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions` {#list-pacticipant-versions-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-get}

**List a pacticipant's versions**

The versions recorded for this pacticipant, latest recorded first, each with the branches it was recorded on and its tags. `branch` and `tag` narrow the list, so the first row of `?branch=main` is the head of `main` and the first row of `?tag=prod` is the latest version tagged `prod`. `state=deleted` lists the deleted versions instead, with `delete_cause` and `purge_after`.

Pass the previous page's `next_cursor` as `cursor` until `has_more` is false.

Requires `pacts:view`.

Operation id: `list_pacticipant_versions_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `branch` | query | string or null | no | Only versions recorded on this branch. |
| `tag` | query | string or null | no | Only versions carrying this tag. |
| `state` | query | string | no | `live` (the default) or `deleted`: what was deleted and is waiting to be purged. |
| `limit` | query | integer | no | Page size. At most 200. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a pacticipant's versions. | `application/json` [`PacticipantVersionListResponse`](#schema-pacticipantversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}` {#read-pacticipant-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-get}

**Read one version**

Read a version by its number, with the branches it was recorded on and its tags.

Requires `pacts:view`.

Operation id: `read_pacticipant_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one version. | `application/json` [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}` {#put-pacticipant-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-put}

**Record a version**

Record that a build produced version `number` of this pacticipant, optionally with the branch it was built from and tags. Safe to repeat:

- **A version is created once and never changes.** The first request answers `201` and stores `build_url`. A later request for the same number answers `200` with the stored version; its `build_url` is not replaced.
- **A branch head only moves forward.** The version is added to `branch`, and becomes its head only when it was recorded later than the current head (`head_moved`). Recording an older version on a branch does not move the head back.
- **Tags are added once.** Sending a tag the version already has changes nothing.

The version number is stored exactly as sent. It cannot contain a `/` here, because it is a path segment.

Requires `pacts:create`.

Operation id: `put_pacticipant_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for record a version.

- `application/json` — [`PacticipantVersionInput`](#schema-pacticipantversioninput) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a version. | `application/json` [`RecordedPacticipantVersion`](#schema-recordedpacticipantversion) |
| 201 | The version was created by this request. | `application/json` [`RecordedPacticipantVersion`](#schema-recordedpacticipantversion) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}` {#remove-pacticipant-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-delete}

**Delete a version**

Delete one version — and with it its pacts, the verification results it published, its deployments and releases, branch membership and tags. The delete is soft: the version disappears from every read (the matrix and can-i-deploy included) at once, `POST …/restore` brings it back for `APIOME_PACT_DELETION_GRACE_DAYS` (default 30) days, and it is then purged. A branch it headed falls back to its latest remaining version. The number can be recorded again at once, as a new version.

A version that is currently deployed or released is refused (`409 pacticipant-version-in-use`) unless `force=true`. `reason` is stored and audited.

Requires `pacts:delete`.

Operation id: `remove_pacticipant_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `reason` | query | string or null | no | Why; stored with the delete and audited. |
| `force` | query | boolean | no | Delete even when a version is currently deployed or released. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a version. | — |
| 409 | `pacticipant-version-in-use`: the version is deployed or released. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}/restore` {#restore-deleted-version-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-restore-post}

**Restore a deleted version**

Undo a version's delete (on its own or by a retention run) before it is purged: its pacts, results and deployments come back, and a branch whose head it was is headed by it again. `409 pacticipant-restore-conflict` when a live version has taken the number since.

Requires `pacts:delete`.

Operation id: `restore_deleted_version_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__restore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for restore a deleted version. | `application/json` [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}/tags/{tag}` {#put-pacticipant-version-tag-v1-tenants-tenant-slug-pacticipants-pacticipant-ref-versions-number-tags-tag-put}

**Tag a version**

Put a tag on a recorded version. Tagging a version that already has the tag changes nothing and answers the same way. A tag may contain `/` (`feat/new-invoice`).

Requires `pacts:create`.

Operation id: `put_pacticipant_version_tag_v1_tenants__tenant_slug__pacticipants__pacticipant_ref__versions__number__tags__tag__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant_ref` | path | string | yes | Path parameter identifying the pacticipant ref segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `tag` | path | string | yes | Path parameter identifying the tag segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for tag a version. | `application/json` [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AgentSettings` {#schema-agentsettings}

The **Agents** switches (``PUT …/pact-contract-settings/agents``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `read` | boolean | no | Agents may read pacts, verdicts and can-i-deploy. |
| `draft` | boolean | no | Agents may draft a pact for a person to review. No agent tool drafts yet; it applies when one ships. |
| `publish` | boolean | no | Agents may publish pacts and provider contracts, never on a main branch. No agent tool publishes yet; it applies when one ships. |
| `record` | boolean | no | Agents may record deployments, never to an environment marked production. |

### `CaptureLink` {#schema-capturelink}

A private capture URL (never its token, except right after it is created).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `project` | string | yes | Project. |
| `version` | string | yes | Version. |
| `consumer` | string | yes | Consumer. |
| `consumer_version` | string | yes | Consumer Version. |
| `token_prefix` | string | yes | Token Prefix. |
| `state` | enum `"live"`, `"revoked"`, `"expired"` | yes | State. |
| `created_by_label` | string or null | no | Created By Label. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `expires_at` | string (date-time) | yes | Expires At timestamp (ISO 8601). |
| `revoked_at` | string (date-time) or null | no | Revoked At timestamp (ISO 8601). |

### `CaptureLinkCreate` {#schema-capturelinkcreate}

``POST …/pact-captures/links``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project` | string | yes | Project slug of the mocked API. |
| `version` | string | yes | Version label of the mocked API. |
| `consumer` | string | yes | Whose calls these are (`Orders UI`). |
| `consumer_version` | string | yes | That consumer's version (`3.4.0`). |
| `expires_in_days` | integer | no | Expires In Days. |

### `CaptureLinkCreated` {#schema-capturelinkcreated}

A new capture URL with its token — shown this once.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `project` | string | yes | Project. |
| `version` | string | yes | Version. |
| `consumer` | string | yes | Consumer. |
| `consumer_version` | string | yes | Consumer Version. |
| `token_prefix` | string | yes | Token Prefix. |
| `state` | enum `"live"`, `"revoked"`, `"expired"` | yes | State. |
| `created_by_label` | string or null | no | Created By Label. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `expires_at` | string (date-time) | yes | Expires At timestamp (ISO 8601). |
| `revoked_at` | string (date-time) or null | no | Revoked At timestamp (ISO 8601). |
| `token` | string | yes | Token. |
| `path` | string | yes | `/{tenant}/{project}/{version}/~capture/{token}`; append the API path. |
| `url` | string | yes | URL. |

### `CaptureLinkList` {#schema-capturelinklist}

A page of capture URLs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `links` | array of [`CaptureLink`](#schema-capturelink) | yes | Links. |
| `count` | integer | yes | Number of count. |
| `has_more` | boolean | yes | Whether more. |
| `next_cursor` | string or null | no | Next Cursor. |

### `CaptureSessionDetail` {#schema-capturesessiondetail}

A session and a page of its calls.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `session` | `CaptureSession` | yes | Session. |
| `calls` | array of `CaptureCall` | yes | Calls. |
| `count` | integer | yes | Number of count. |
| `has_more` | boolean | yes | Whether more. |
| `next_cursor` | string or null | no | Next Cursor. |

### `CaptureSessionList` {#schema-capturesessionlist}

A page of sessions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sessions` | array of `CaptureSession` | yes | Sessions. |
| `count` | integer | yes | Number of count. |
| `has_more` | boolean | yes | Whether more. |
| `next_cursor` | string or null | no | Next Cursor. |
| `retention_days` | integer | yes | Retention Days. |

### `CaptureSettings` {#schema-capturesettings}

How long captures are kept, and calls refused for the whole workspace.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `retention_days` | integer | yes | Days a capture is kept after it is recorded. |
| `configured` | boolean | yes | `false` while the default is in force. |
| `refused_calls` | integer | yes | Tagged calls no session could take (the workspace had too many). |
| `last_refused_reason` | string or null | no | Last Refused Reason. |
| `last_refused_at` | string (date-time) or null | no | Last Refused At timestamp (ISO 8601). |
| `updated_by_label` | string or null | no | Updated By Label. |
| `updated_at` | string (date-time) or null | no | Last update timestamp (ISO 8601). |
| `can_edit` | boolean | yes | Whether the caller may change the retention (`pacts:delete`). |
| `limits` | `CaptureLimits` | yes | Limits. |

### `CaptureSettingsSave` {#schema-capturesettingssave}

``PUT …/pact-captures/settings``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `retention_days` | integer | yes | Days to keep captures. |

### `CommitStatusList` {#schema-commitstatuslist}

A page of commit statuses, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of [`CommitStatusRecord`](#schema-commitstatusrecord) | yes | Items. |
| `next_cursor` | string or null | no | Pass as `cursor` for the next page. |

### `CommitStatusRecord` {#schema-commitstatusrecord}

A recorded commit status, as the API returns it.

Never carries a token: the credential is resolved at send time and stored nowhere.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Status id. |
| `pacticipant` | string | yes | Handle of the pacticipant whose commit the status is on. |
| `version` | string | yes | The pacticipant version (commit) the status is about. |
| `consumer` | string | yes | Handle of the pair's consumer. |
| `provider` | string | yes | Handle of the pair's provider. |
| `side` | enum `"consumer"`, `"provider"` | yes | Which pacticipant of the pair the status is for. |
| `context` | string | yes | Status context, `apiome-pact/<consumer>/<provider>`. |
| `state` | enum `"pending"`, `"pass"`, `"fail"` | yes | The verdict. |
| `description` | string | no | The one-line description shown on the commit. |
| `target_url` | string or null | no | Where the status links. |
| `pact_version_sha` | string or null | no | The pact content the verdict is about. |
| `verification_number` | integer or null | no | The verification result, for a verdict. |
| `commit_sha` | string or null | no | The commit the status was written to. |
| `git_provider` | string or null | no | `github` or `gitlab`, once a repository matched. |
| `repository` | string or null | no | Full name of the repository written to. |
| `repository_id` | string or null | no | The registered repository used. |
| `outcome` | enum `"queued"`, `"dispatched"`, `"suppressed"`, `"failed"` | yes | `dispatched` (accepted), `suppressed` (not attempted — see `reason_code`), `failed` or `queued`. |
| `reason_code` | string or null | no | Stable reason for a suppressed or failed status. |
| `message` | string | no | What happened, in words. |
| `http_status` | integer or null | no | The provider's HTTP status, when a request went out. |
| `attempts` | integer | no | How many times the status was sent. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |

### `CommitStatusSettings` {#schema-commitstatussettings}

The **CI and commit statuses** switches (``PUT …/pact-contract-settings/commit-statuses``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer_commit` | boolean | no | Write pact verdicts (awaiting verification, verified, failed) on the consumer's commit. |
| `provider_commit` | boolean | no | Write verification verdicts on the provider's commit. |
| `bidirectional` | boolean | no | Bi-directional verdicts set commit statuses and fire their webhooks, as a verification does. |

### `ContractSettings` {#schema-contractsettings}

``GET …/pact-contract-settings``: both groups of switches.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `commit_statuses` | [`CommitStatusSettings`](#schema-commitstatussettings) | yes | Commit Statuses. |
| `agents` | [`AgentSettings`](#schema-agentsettings) | yes | Agents. |
| `configured` | boolean | yes | Whether the workspace saved any switch; `false` shows the defaults. |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `updated_by` | string or null | no | Updated By. |
| `can_edit` | boolean | yes | Whether the caller may change the switches (`pacts:delete`). |

### `ContractSourcesInput` {#schema-contractsourcesinput}

The standing sources of a provider contract, replaced as a whole.

Attributes:
    on_project_publish: Publish each published version of the bound project.
    repository: Publish a repository file on every push, or ``None`` for no repository source.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `onProjectPublish` | boolean | no | Publish each published version of the bound project as the provider contract. |
| `repository` | `RepositorySourceInput` or null | no | Publish a repository file on every push; `null` for none. |

### `ContractSourcesRecord` {#schema-contractsourcesrecord}

A provider pacticipant's standing contract sources, as stored.

Attributes:
    pacticipant: The pacticipant's handle.
    on_project_publish: Whether each published version of the bound project is published.
    project: The bound project (``None`` when the pacticipant is bound to none).
    repository: The repository source, or ``None``.
    warnings: Why a stored source will not fire right now (no project, repository deleted,
        no push webhook).
    updated_at: When the setting last changed; ``None`` when it was never set.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pacticipant` | string | yes | Pacticipant. |
| `onProjectPublish` | boolean | no | On Project Publish. |
| `project` | `ProjectSourceRecord` or null | no | Project. |
| `repository` | `RepositorySourceRecord` or null | no | Repository. |
| `warnings` | array of string | no | Warnings. |
| `updatedAt` | string or null | no | Updated At. |

### `DeletedPage` {#schema-deletedpage}

A page of the Recently deleted list, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `DeletedItem` | yes | Items. |
| `count` | integer | yes | Number of count. |
| `has_more` | boolean | yes | Whether more. |
| `next_cursor` | string or null | no | Next Cursor. |
| `restore_window_days` | integer | yes | Restore Window Days. |
| `can_restore` | boolean | yes | Whether the caller may restore (`pacts:delete`). |

### `DeletionImpact` {#schema-deletionimpact}

What deleting one pacticipant would take with it, and whether it may be deleted now.

Attributes:
    slug: The pacticipant's handle.
    name: Its name.
    versions: Live versions that would be deleted.
    pacts: Distinct pacts naming it, as consumer or provider.
    verification_results: Verification results of those pacts.
    providers: Providers that would lose it as a consumer (at most :data:`MAX_NAMES`).
    providers_total: How many providers in all.
    consumers: Consumers that would lose it as a provider (at most :data:`MAX_NAMES`).
    consumers_total: How many consumers in all.
    in_use: Versions currently deployed or released (at most :data:`MAX_NAMES`).
    blocked: Whether the delete is refused now (a version is in use).
    grace_days: Days the delete can be undone before it is purged.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `versions` | integer | yes | Live versions that would be deleted. |
| `pacts` | integer | yes | Distinct pacts naming it, as consumer or provider. |
| `verification_results` | integer | yes | Verification results of those pacts. |
| `providers` | array of string | no | Providers that lose it as a consumer. |
| `providers_total` | integer | no | Providers Total. |
| `consumers` | array of string | no | Consumers that lose it as a provider. |
| `consumers_total` | integer | no | Consumers Total. |
| `in_use` | array of string | no | Versions deployed or released now; while any is, the delete is refused. |
| `blocked` | boolean | yes | Whether the delete is refused now: record the undeployment first. |
| `grace_days` | integer | yes | Days the delete can be undone (`POST …/restore`) before it is purged. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LabelNameListResponse` {#schema-labelnamelistresponse}

One page of the workspace's distinct labels.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `labels` | array of `LabelName` | no | By name. |
| `count` | integer | yes | How many labels were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PactSetupPullRequestsRequest` {#schema-pactsetuppullrequestsrequest}

``POST …/pact-setup/github/pull-requests``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repositories` | array of `PactSetupPullRequestRepository` | yes | Repositories. |
| `environment` | string | yes | The environment can-i-deploy asks about. |
| `can_i_deploy` | boolean | no | Add the can-i-deploy step. |
| `record_deployment` | boolean | no | Add the record-deployment step. |
| `preview` | boolean | no | Only answer with the file each pull request would add; GitHub is not called. |

### `PactSetupPullRequestsResponse` {#schema-pactsetuppullrequestsresponse}

Every repository asked for.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `results` | array of `PactSetupPullRequestResult` | yes | Results. |

### `PactSetupSave` {#schema-pactsetupsave}

``PUT …/pact-setup``: only what is sent changes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mark` | map of boolean or null | no | Sections to mark done (`true`) or unmark (`false`); the others keep their mark. |
| `first_pact_path` | enum `"tests"`, `"spec"` or null | no | The chosen first-pact path. |
| `ci_key` | `PactSetupCiKey` or null | no | The key just created for CI. |
| `forget_ci_key` | boolean | no | Forget the recorded CI key (it is not revoked). |

### `PactSetupSecretsRequest` {#schema-pactsetupsecretsrequest}

``POST …/pact-setup/github/secrets``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repository_ids` | array of string | yes | Registered repositories to write to. |
| `broker_base_url` | string | yes | What `PACT_BROKER_BASE_URL` is set to. |
| `token` | string | yes | What `PACT_BROKER_TOKEN` is set to: an Apiome API key. Sent on to GitHub sealed; never stored. |

### `PactSetupSecretsResponse` {#schema-pactsetupsecretsresponse}

Every repository asked for, written or skipped with the reason.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `results` | array of `PactSetupSecretsResult` | yes | Results. |

### `PactSetupState` {#schema-pactsetupstate}

``GET …/pact-setup``: the six sections and everything the page draws them from.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sections` | array of `PactSetupSection` | yes | Sections. |
| `done` | integer | yes | How many sections are done. |
| `total` | integer | yes | How many there are (6). |
| `complete` | boolean | yes | Whether all are done. |
| `facts` | `PactSetupFacts` | yes | Facts. |
| `saved` | `PactSetupSaved` | yes | Saved. |
| `candidates` | array of `PactSetupCandidate` | no | Candidates. |
| `candidates_omitted` | integer | no | Candidates left out of `candidates` because the list is capped. |
| `github` | `PactSetupGithub` | yes | Github. |
| `workflow_path` | string | yes | Where the pull request puts the workflow. |
| `can_edit` | boolean | yes | Whether the caller may act on the page (`pacts:delete`). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `updated_by` | string or null | no | Updated By. |

### `PacticipantBranchListResponse` {#schema-pacticipantbranchlistresponse}

One page of a pacticipant's branches.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `branches` | array of `PacticipantBranchRecord` | no | By name. |
| `count` | integer | yes | How many branches were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantInput` {#schema-pacticipantinput}

A new pacticipant.

Attributes:
    name: The name pacts use, as a Pact file or a person writes it.
    slug: The handle; derived from ``name`` when omitted, and never editable.
    display_name: What people read, when it differs from ``name``.
    repository_url: http(s) URL of the application's source repository.
    main_branch: The branch read by default when a query names none.
    project: Slug or id of the Apiome project that describes this provider.
    consumer_id: Id of this application's row in the consumer registry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | The name pacts use, as a Pact file or a person writes it. |
| `slug` | string or null | no | The handle URLs and CI name. Derived from `name` when omitted; not editable afterwards. |
| `display_name` | string or null | no | What people read, when it differs from `name`. |
| `repository_url` | string or null | no | http(s) URL of the application's source repository. |
| `main_branch` | string or null | no | The branch read by default when a query names none. |
| `project` | string or null | no | Slug or id of the project that describes this application as a provider. |
| `consumer_id` | string or null | no | Id of this application's consumer in the consumer registry. |

### `PacticipantLabelListResponse` {#schema-pacticipantlabellistresponse}

One page of a pacticipant's labels.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `labels` | array of [`PacticipantLabelRecord`](#schema-pacticipantlabelrecord) | no | By name. |
| `count` | integer | yes | How many labels were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantLabelRecord` {#schema-pacticipantlabelrecord}

A label on a pacticipant.

Attributes:
    name: The label.
    pacticipant_id: The labelled pacticipant.
    pacticipant_slug: Its handle.
    pacticipant_name: Its display name.
    created_at: When the label was added.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `pacticipant_id` | string | yes | Pacticipant ID. |
| `pacticipant_slug` | string | yes | Pacticipant Slug. |
| `pacticipant_name` | string | yes | Pacticipant Name. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |

### `PacticipantListResponse` {#schema-pacticipantlistresponse}

One page of the tenant's pacticipants.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pacticipants` | array of [`PacticipantRecord`](#schema-pacticipantrecord) | no | By handle. |
| `count` | integer | yes | How many pacticipants were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantPatch` {#schema-pacticipantpatch}

A partial update of a pacticipant. An omitted field is left alone; ``null`` clears it.

Attributes:
    name: New name pacts use (cannot be cleared). Renaming keeps the handle and the history;
        the old name and the new one both resolve to this pacticipant afterwards.
    display_name: New display name, or ``null`` to clear it.
    repository_url: New repository URL, or ``null`` to clear it.
    main_branch: New main branch, or ``null`` to clear it.
    project: Slug or id of the project to bind, or ``null`` to unbind.
    consumer_id: Id of the consumer to bind, or ``null`` to unbind.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Rename: the new name pacts use. The handle and the history stay; the old name keeps resolving. `409 pacticipant-slug-taken` when another pacticipant has that name. |
| `display_name` | string or null | no | New display name; `null` clears it. |
| `repository_url` | string or null | no | New repository URL; `null` clears it. |
| `main_branch` | string or null | no | New main branch; `null` clears it. |
| `project` | string or null | no | Project slug or id to bind; `null` unbinds. |
| `consumer_id` | string or null | no | Consumer id to bind; `null` unbinds. |

### `PacticipantRecord` {#schema-pacticipantrecord}

A stored pacticipant.

Attributes:
    id: Row id.
    tenant_id: Owning tenant.
    slug: Stable handle.
    name: The name pacts use.
    display_name: What people read; ``None`` reads as ``name``.
    aliases: The other names it has had, oldest first; each still resolves to it.
    repository_url: Source repository URL.
    main_branch: The branch read by default.
    project_id: Bound project, when this is a provider described in Apiome.
    consumer_id: Bound consumer-registry row, when this is a registered consumer.
    labels: Its labels, by name.
    created_at: When it was registered.
    updated_at: When it was last changed.
    deleted_at: When it was deleted; ``None`` while it is live.
    deleted_by_label: Who deleted it, as text.
    delete_reason: Why, as the caller said.
    purge_after: When the deleted pacticipant is removed for good, unless restored first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `display_name` | string or null | no | What people read; null reads as `name`. |
| `aliases` | array of string | no | Other names it has had (PFX-8.10), oldest first. Each still resolves to this pacticipant. |
| `repository_url` | string or null | no | Repository URL. |
| `main_branch` | string or null | no | Main Branch. |
| `project_id` | string or null | no | Project identifier the resource belongs to. |
| `consumer_id` | string or null | no | Consumer ID. |
| `labels` | array of string | no | Its labels, by name. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `deleted_at` | string or null | no | When it was deleted; null while it is live. |
| `deleted_by_label` | string or null | no | Who deleted it. |
| `delete_reason` | string or null | no | Why it was deleted. |
| `purge_after` | string or null | no | When a deleted pacticipant is removed for good, unless it is restored first. |

### `PacticipantVersionInput` {#schema-pacticipantversioninput}

What a build reports when it records a version.

Attributes:
    build_url: http(s) URL of the CI build. Kept only when this request creates the version.
    branch: The repository branch the version was built from.
    tags: Tags to put on the version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `build_url` | string or null | no | http(s) URL of the CI build. Stored only when this request creates the version. |
| `branch` | string or null | no | The repository branch this version was built from. |
| `tags` | array of string | no | Tags to put on the version (at most 50). |

### `PacticipantVersionListResponse` {#schema-pacticipantversionlistresponse}

One page of a pacticipant's versions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versions` | array of [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) | no | Latest recorded first. |
| `count` | integer | yes | How many versions were returned. |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |

### `PacticipantVersionRecord` {#schema-pacticipantversionrecord}

A stored pacticipant version.

Attributes:
    id: Row id.
    pacticipant_id: Owning pacticipant.
    number: The version string, as the build reported it.
    seq: Order of recording; a higher value was recorded later.
    build_url: The CI build that produced it.
    branches: Branches it was recorded on, by name.
    tags: Its tags, by name.
    created_by: The user who recorded it, when still known.
    actor_label: Who recorded it, as text.
    created_at: When it was recorded.
    deleted_at: When it was deleted; ``None`` while it is live.
    deleted_by_label: Who deleted it, as text.
    delete_reason: Why, as the caller said.
    delete_cause: ``version``, ``pacticipant`` or ``retention`` (see :data:`DELETE_CAUSES`).
    purge_after: When the deleted version is removed for good, unless restored first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `pacticipant_id` | string | yes | Pacticipant ID. |
| `number` | string | yes | Number. |
| `seq` | integer | yes | Order of recording; a higher value was recorded later. |
| `build_url` | string or null | no | Build URL. |
| `branches` | array of string | no | Branches. |
| `tags` | array of string | no | Associated tag labels. |
| `created_by` | string or null | no | Created By. |
| `actor_label` | string or null | no | Actor Label. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `deleted_at` | string or null | no | When it was deleted; null while it is live. |
| `deleted_by_label` | string or null | no | Who deleted it. |
| `delete_reason` | string or null | no | Why it was deleted. |
| `delete_cause` | string or null | no | `version` (deleted on its own), `pacticipant` (with its pacticipant) or `retention`. |
| `purge_after` | string or null | no | When a deleted version is removed for good, unless it is restored first. |

### `RecordedPacticipantVersion` {#schema-recordedpacticipantversion}

The outcome of recording a version.

Attributes:
    version: The version as stored, with every branch and tag it now has.
    created: Whether this request created the version (false: it already existed, unchanged).
    head_moved: Whether the named branch's head moved to this version.
    branch_created: Whether the named branch did not exist before this request.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | [`PacticipantVersionRecord`](#schema-pacticipantversionrecord) | yes | Version. |
| `created` | boolean | yes | False when the version already existed; it is returned unchanged. |
| `head_moved` | boolean | no | Whether the branch named in the request now has this version as its head. |
| `branch_created` | boolean | no | Whether this request recorded the first version on the named branch. |

### `RetentionPlan` {#schema-retentionplan}

The answer to a retention run: the plan, and whether it was applied.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `dry_run` | boolean | yes | Dry Run. |
| `applied` | boolean | yes | Whether the deletions were made. |
| `plan_digest` | string | yes | Send this back with `dry_run: false` to apply exactly this plan. |
| `keep` | `RetentionKeep` | yes | Keep. |
| `evaluated` | integer | yes | Evaluated. |
| `kept` | integer | yes | Kept. |
| `deleted` | integer | yes | Deleted. |
| `remaining` | integer | no | Deletions past this run's cap; run again to make them. |
| `pacts` | integer | no | Pacts published from the deleted versions, which go with them. |
| `results` | integer | no | Verification results of the deleted versions, which go with them. |
| `matched_by` | map of integer | no | Versions each rule matches on its own (a version two rules match is counted under both), so a rule can say how much it keeps. |
| `max_deletions` | integer | no | Max Deletions. |
| `grace_days` | integer | yes | Days a deleted version can still be restored before it is purged. |
| `pacticipants` | array of `PacticipantPlan` | no | Pacticipants. |

### `RetentionPolicy` {#schema-retentionpolicy}

A workspace's clean-up rules as ``GET …/pact-retention/policy`` answers them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `keep_deployed_or_released` | boolean | no | Every version deployed or released anywhere is kept. Always `true`: `false` is refused. |
| `keep_main_branch_latest` | integer or null | no | Keep the newest N versions of each pacticipant's main branch. |
| `keep_other_branch_latest` | integer or null | no | Keep the newest N versions of every other branch. |
| `keep_other_branch_days` | integer or null | no | With `keep_other_branch_latest`: only while they were recorded in the last D days. |
| `keep_tags` | array of string | no | Keep every version carrying one of these tags (at most 50). |
| `nightly_enabled` | boolean | no | Apply the rules every night. Off: clean-up removes nothing. |
| `restore_window_days` | integer | no | Days a deleted pacticipant or version can be restored before it is purged. |
| `configured` | boolean | yes | Whether the workspace has saved rules; `false` shows the defaults. |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `updated_by` | string or null | no | Who saved them last. |
| `last_run` | `RetentionLastRun` or null | no | Last Run. |
| `next_run_at` | string or null | no | When the nightly clean-up runs next; null while it is off. |
| `can_edit` | boolean | yes | Whether the caller may save the rules and restore (`pacts:delete`); otherwise read-only. |

### `RetentionPreview` {#schema-retentionpreview}

What the rules would remove if clean-up ran now — what the next nightly run removes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `draft` | boolean | yes | Whether this previews rules that are not saved. |
| `nightly_enabled` | boolean | yes | Off: nothing is removed while clean-up is off. |
| `next_run_at` | string or null | no | Next Run At timestamp (ISO 8601). |
| `plan` | [`RetentionPlan`](#schema-retentionplan) | yes | Plan. |

### `RetentionPreviewRequest` {#schema-retentionpreviewrequest}

``POST …/pact-retention/policy/preview``: preview the saved rules, or a draft of them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rules` | [`RetentionRules`](#schema-retentionrules) or null | no | Rules not saved yet; the saved rules when omitted. |

### `RetentionRequest` {#schema-retentionrequest}

One retention run.

Attributes:
    keep: The keep selectors.
    pacticipants: The pacticipants to clean (handles, ids or names); all of them when omitted.
    dry_run: Only plan (the default). ``false`` applies the plan.
    plan_digest: The ``plan_digest`` of the dry run being applied; required with ``dry_run: false``.
    reason: Why, stored on every deleted version and in the audit trail.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `keep` | `RetentionKeep` | yes | Keep. |
| `pacticipants` | array of string or null | no | Handles, ids or names to clean (at most 200); every pacticipant when omitted. |
| `dry_run` | boolean | no | Only answer the plan. `false` applies it. |
| `plan_digest` | string or null | no | The `plan_digest` of the dry run being applied. Required when `dry_run` is false. |
| `reason` | string or null | no | Why; stored on each deleted version (≤ 500 characters). |

### `RetentionRules` {#schema-retentionrules}

The clean-up rules a workspace saves (``PUT …/pact-retention/policy``).

A field left out takes its default: a ``PUT`` replaces every rule. ``apiome pact retention set``
reads the rules first and changes only the flags it is given.

Attributes:
    keep_deployed_or_released: Always ``true``; ``false`` is refused.
    keep_main_branch_latest: Keep the newest N versions of each pacticipant's main branch.
    keep_other_branch_latest: Keep the newest N versions of every other branch.
    keep_other_branch_days: With ``keep_other_branch_latest``: only while recorded in the last D days.
    keep_tags: Keep every version carrying one of these tags.
    nightly_enabled: Apply the rules every night.
    restore_window_days: Days a deleted pacticipant or version stays restorable.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `keep_deployed_or_released` | boolean | no | Every version deployed or released anywhere is kept. Always `true`: `false` is refused. |
| `keep_main_branch_latest` | integer or null | no | Keep the newest N versions of each pacticipant's main branch. |
| `keep_other_branch_latest` | integer or null | no | Keep the newest N versions of every other branch. |
| `keep_other_branch_days` | integer or null | no | With `keep_other_branch_latest`: only while they were recorded in the last D days. |
| `keep_tags` | array of string | no | Keep every version carrying one of these tags (at most 50). |
| `nightly_enabled` | boolean | no | Apply the rules every night. Off: clean-up removes nothing. |
| `restore_window_days` | integer | no | Days a deleted pacticipant or version can be restored before it is purged. |
