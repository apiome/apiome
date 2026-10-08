---
title: "Slate security"
description: "REST endpoints tagged slate-security: 19 operations."
sidebar_position: 66
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-security` · 19 operations

## `GET /v1/slate/environments/{environment_id}/security` {#get-security-policy-v1-slate-environments-environment-id-security-get}

**Get Security Policy**

Return a lane's security policy, its rules and carve-outs, and what it actually enforces.

Operation id: `get_security_policy_v1_slate_environments__environment_id__security_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security policy. | `application/json` [`SecurityPolicyResponse`](#schema-securitypolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/approvals` {#record-security-approval-v1-slate-environments-environment-id-security-approvals-post}

**Record Security Approval**

Record the approving half of dual control.

The approver is always the *authenticated caller* — there is no field by which one person can
record somebody else's approval, which is the only version of two-person review that means
anything. Approving one's own change is refused here as ``approval-self`` and again by V188's
``CHECK (approver_actor_key <> author_actor_key)``.

Operation id: `record_security_approval_v1_slate_environments__environment_id__security_approvals_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record security approval.

- `application/json` — [`SlateSecurityApprovalRequest`](#schema-slatesecurityapprovalrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record security approval. | `application/json` [`SlateSecurityApprovalBody`](#schema-slatesecurityapprovalbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/security/audit` {#get-security-audit-v1-slate-environments-environment-id-security-audit-get}

**Get Security Audit**

Return a lane's append-only security audit trail, most recent first.

Operation id: `get_security_audit_v1_slate_environments__environment_id__security_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security audit. | `application/json` [`SlateSecurityAuditResponse`](#schema-slatesecurityauditresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/security/audit/export` {#export-security-audit-v1-slate-environments-environment-id-security-audit-export-get}

**Export Security Audit**

Export a lane's security audit trail as CSV.

Modelled on ``access_routes.py``'s exporter, and fixing the two defects that precedent
carries.

**CSV injection is neutralized.** A cell whose first character is ``=``, ``+``, ``-``, ``@``,
a tab or a carriage return is prefixed with an apostrophe. An actor display name and a
refusal detail are attacker-influenced text, and the existing exporter writes them raw, so
opening the evidence in a spreadsheet is a code-execution path.

**Nothing is silently truncated.** The existing exporter caps at 1000 rows with no signal,
which in compliance evidence is a correctness bug rather than a performance choice: an
auditor reading a truncated ledger concludes the missing entries never happened. This one
reads one row past the cap, and when there are more it emits a final row saying so in words.

Reading the evidence is itself audit-worthy — who exported the record of who disabled the WAF
is part of that record — so an ``export`` audit row is written before the download begins.

Operation id: `export_security_audit_v1_slate_environments__environment_id__security_audit_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export security audit. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/security/events` {#get-security-events-v1-slate-environments-environment-id-security-events-get}

**Get Security Events**

Return a lane's security events, most recent first.

The filter names are the designer's dimension ids unchanged, so filtering on screen and
filtering in a query cannot mean different things.

Operation id: `get_security_events_v1_slate_environments__environment_id__security_events_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `ruleRef` | query | string or null | no | Query parameter: rule ref. |
| `action` | query | string or null | no | Query parameter: action. |
| `route` | query | string or null | no | Query parameter: route. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `source` | query | string or null | no | Source material descriptor (file, URL, paste, or discovery). |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security events. | `application/json` [`SecurityEventsResponse`](#schema-securityeventsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/security/events/{event_id}` {#get-security-event-v1-slate-environments-environment-id-security-events-event-id-get}

**Get Security Event**

Return one security event with its redacted evidence.

Operation id: `get_security_event_v1_slate_environments__environment_id__security_events__event_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `event_id` | path | string | yes | Path parameter identifying the event id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security event. | `application/json` [`SecurityEventBody`](#schema-securityeventbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/exceptions` {#create-security-exception-v1-slate-environments-environment-id-security-exceptions-post}

**Create Security Exception**

Open a scoped, expiring carve-out.

An exception is a hole. §29.4 wants them possible; keeping them scoped and bounded is what
stops them becoming the policy, so an unbounded or over-long carve-out is refused with no
acknowledgement path.

Operation id: `create_security_exception_v1_slate_environments__environment_id__security_exceptions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create security exception.

- `application/json` — [`CreateExceptionRequest`](#schema-createexceptionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create security exception. | `application/json` [`ExceptionResponse`](#schema-exceptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/security/exceptions/{exception_id}` {#remove-security-exception-v1-slate-environments-environment-id-security-exceptions-exception-id-delete}

**Remove Security Exception**

Close a carve-out early.

Operation id: `remove_security_exception_v1_slate_environments__environment_id__security_exceptions__exception_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `exception_id` | path | string | yes | Path parameter identifying the exception id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove security exception. | `application/json` [`DeleteExceptionResponse`](#schema-deleteexceptionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/security/managed-groups/{group_id}` {#set-security-managed-group-v1-slate-environments-environment-id-security-managed-groups-group-id-put}

**Set Security Managed Group**

Move one managed WAF group off, or back onto, its catalog default.

``off`` and ``log`` are the directions that remove protection, so both require a stated
reason — refused here as ``managed-off-without-reason`` and again by V188's
``mode NOT IN ('off','log') OR reason IS NOT NULL``.

Operation id: `set_security_managed_group_v1_slate_environments__environment_id__security_managed_groups__group_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `group_id` | path | string | yes | Path parameter identifying the group id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set security managed group.

- `application/json` — [`SetManagedGroupRequest`](#schema-setmanagedgrouprequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set security managed group. | `application/json` [`SetManagedGroupResponse`](#schema-setmanagedgroupresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/security/presets` {#set-security-presets-v1-slate-environments-environment-id-security-presets-put}

**Set Security Presets**

Change a lane's managed tier and its bot, rate and challenge settings.

Turning the managed ruleset off with no stated reason is refused here with a sentence, and
again by V188's CHECK. Both are deliberate: the operator should meet the explanation, not a
constraint violation, and no future code path should be able to skip the explanation.

Operation id: `set_security_presets_v1_slate_environments__environment_id__security_presets_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set security presets.

- `application/json` — [`SetPresetsRequest`](#schema-setpresetsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set security presets. | `application/json` [`SetPresetsResponse`](#schema-setpresetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/rules` {#create-security-rule-v1-slate-environments-environment-id-security-rules-post}

**Create Security Rule**

Create a custom security rule, refusing an unsafe variant by name.

Operation id: `create_security_rule_v1_slate_environments__environment_id__security_rules_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create security rule.

- `application/json` — [`SlateSecurityWriteRuleRequest`](#schema-slatesecuritywriterulerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create security rule. | `application/json` [`SlateSecurityWriteRuleResponse`](#schema-slatesecuritywriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/security/rules/{rule_id}` {#replace-security-rule-v1-slate-environments-environment-id-security-rules-rule-id-put}

**Replace Security Rule**

Replace a custom security rule, running the same gates as a create.

Operation id: `replace_security_rule_v1_slate_environments__environment_id__security_rules__rule_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace security rule.

- `application/json` — [`SlateSecurityWriteRuleRequest`](#schema-slatesecuritywriterulerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace security rule. | `application/json` [`SlateSecurityWriteRuleResponse`](#schema-slatesecuritywriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/security/rules/{rule_id}` {#remove-security-rule-v1-slate-environments-environment-id-security-rules-rule-id-delete}

**Remove Security Rule**

Remove a custom security rule, keeping its body so the removal can be undone.

Operation id: `remove_security_rule_v1_slate_environments__environment_id__security_rules__rule_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove security rule. | `application/json` [`SlateSecurityDeleteRuleResponse`](#schema-slatesecuritydeleteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/rules/{rule_id}/revert` {#revert-security-rule-v1-slate-environments-environment-id-security-rules-rule-id-revert-post}

**Revert Security Rule**

Restore a rule to a stored revision.

Reverting applies the recorded document rather than reconstructing intent from an audit
sentence, which is what makes §29.4's "every rule change can be reverted" a fact about this
system rather than a claim about it.

Operation id: `revert_security_rule_v1_slate_environments__environment_id__security_rules__rule_id__revert_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for revert security rule.

- `application/json` — [`SlateSecurityRevertRequest`](#schema-slatesecurityrevertrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for revert security rule. | `application/json` [`SlateSecurityWriteRuleResponse`](#schema-slatesecuritywriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/security/rules/{rule_id}/revisions` {#get-security-rule-revisions-v1-slate-environments-environment-id-security-rules-rule-id-revisions-get}

**Get Security Rule Revisions**

Return a rule's revision history, newest first.

Operation id: `get_security_rule_revisions_v1_slate_environments__environment_id__security_rules__rule_id__revisions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security rule revisions. | `application/json` [`SlateSecurityRevisionsResponse`](#schema-slatesecurityrevisionsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/rules/{rule_id}/rollout` {#set-security-rule-rollout-v1-slate-environments-environment-id-security-rules-rule-id-rollout-post}

**Set Security Rule Rollout**

Advance or retreat a rule's staged rollout.

This is where dual control actually bites. A rule can be written in simulate freely; the write
that makes an enforcing ``block`` rule real runs the same
:func:`app.slate_security.evaluate_security_safety` gate as a body edit, so it is refused as
``enforce-without-simulation``, ``enforce-without-approval``, ``approval-stale`` or
``approval-self`` rather than succeeding because it happened to arrive by a different route.

Operation id: `set_security_rule_rollout_v1_slate_environments__environment_id__security_rules__rule_id__rollout_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set security rule rollout.

- `application/json` — [`SlateSecurityRolloutRequest`](#schema-slatesecurityrolloutrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set security rule rollout. | `application/json` [`SlateSecurityWriteRuleResponse`](#schema-slatesecuritywriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/security/simulate` {#simulate-security-request-v1-slate-environments-environment-id-security-simulate-post}

**Simulate Security Request**

Explain what this lane's policy decides for a test request, and why every rule lost.

A read, not a write, unless ``persist`` is set. "Which rule blocked this customer" is the
question that brings an operator here during an incident, so requiring PUBLISH would put the
answer out of reach of exactly the person asking.

Operation id: `simulate_security_request_v1_slate_environments__environment_id__security_simulate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for simulate security request.

- `application/json` — [`SlateSecuritySimulateCommandBody`](#schema-slatesecuritysimulatecommandbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for simulate security request. | `application/json` [`SlateSecuritySimulateResponse`](#schema-slatesecuritysimulateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/security/managed-groups` {#get-managed-group-catalog-v1-slate-security-managed-groups-get}

**Get Managed Group Catalog**

Return the curated WAF group catalog.

Each group states its false-positive risk and what it will break. A group that cannot say what
it will break is a group nobody can safely enable, so the catalog is the answer rather than a
list of names.

Operation id: `get_managed_group_catalog_v1_slate_security_managed_groups_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get managed group catalog. | `application/json` [`ManagedGroupsResponse`](#schema-managedgroupsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/security/presets` {#get-security-presets-v1-slate-security-presets-get}

**Get Security Presets**

Return every managed tier and safe preset as data.

A preset is its fields, not its name. "Aggressive" is not a mood the system interprets at
request time, and an operator choosing it is entitled to read what it will do to their
readers before they choose — which is why ``expectedImpact`` is a required field on all three
families rather than documentation somewhere else.

Operation id: `get_security_presets_v1_slate_security_presets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get security presets. | `application/json` [`SecurityPresetsResponse`](#schema-securitypresetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CreateExceptionRequest` {#schema-createexceptionrequest}

Open a scoped, expiring carve-out.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjectKind` | enum `"managed-group"`, `"rule"`, `"policy"` | yes | What the carve-out applies to. |
| `subjectRef` | string | no | Group catalog id or rule id. |
| `matcherKind` | string | no | Matcher Kind. |
| `matcherValue` | string | yes | The route pattern the exception covers. |
| `expiresAt` | string | yes | When it lapses. An exception that cannot lapse is policy. |
| `reason` | string | yes | Why it exists. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Dry Run. |

### `DeleteExceptionResponse` {#schema-deleteexceptionresponse}

The outcome of closing a carve-out early.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | Deleted. |
| `dryRun` | boolean | yes | Dry Run. |
| `policyVersion` | integer | yes | Policy Version. |

### `ExceptionResponse` {#schema-exceptionresponse}

The outcome of opening a carve-out.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `exception` | `SecurityExceptionBody` or null | no | Exception. |
| `policyVersion` | integer | yes | The version after the write. |
| `warnings` | array of `SecurityWarningBody` | no | Warnings. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ManagedGroupsResponse` {#schema-managedgroupsresponse}

The curated group catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `groups` | array of `ManagedGroupBody` | yes | Every group, in catalog order. |

### `SecurityEventBody` {#schema-securityeventbody}

One security event, with its redacted evidence.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `at` | string or null | no | At. |
| `source` | string | no | Provenance source for the record (for example human or imported). |
| `ruleKind` | string | no | Rule Kind. |
| `ruleRef` | string | no | Rule Ref. |
| `ruleLabel` | string | no | Rule Label. |
| `route` | string | no | Route. |
| `method` | string | no | Method. |
| `releaseId` | string or null | no | Release ID. |
| `region` | string or null | no | Region. |
| `action` | string | no | Action. |
| `mitigated` | boolean | no | Mitigated. |
| `edgeAttached` | boolean | no | Edge Attached. |
| `evidence` | map of string | no | Evidence. |
| `retainUntil` | string or null | no | Retain Until. |

### `SecurityEventsResponse` {#schema-securityeventsresponse}

A lane's security events.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `events` | array of [`SecurityEventBody`](#schema-securityeventbody) | yes | Most recent first. |
| `observed` | boolean | no | False: none of these were observed in a request path. |
| `sentence` | string | no | Sentence. |

### `SecurityPolicyResponse` {#schema-securitypolicyresponse}

A lane's complete security policy, and what it actually enforces.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | The lane. |
| `managedRuleset` | string | yes | Active managed tier. |
| `botPreset` | string | yes | Active bot preset. |
| `ratePreset` | string | yes | Active rate preset. |
| `challengeMode` | string | yes | off, managed or always. |
| `presetOverrides` | object | no | Preset Overrides. |
| `managedOffReason` | string or null | no | Managed Off Reason. |
| `policyVersion` | integer | yes | Optimistic-concurrency token. |
| `edgeAttached` | boolean | yes | Whether a delivery tier serves this lane. |
| `edgeProvider` | string or null | no | Edge Provider. |
| `enforcement` | `SlateSecurityEnforcementBody` | no | Whether the policy stops anything. |
| `ddos` | `DdosBody` | no | DDoS status, or its absence. |
| `groups` | array of `ManagedGroupBody` | yes | The catalog with this lane's overrides. |
| `rules` | array of `SecurityRuleBody` | yes | Custom rules, in precedence order. |
| `exceptions` | array of `SecurityExceptionBody` | yes | Carve-outs, soonest first. |
| `rulesDigest` | string | yes | Determinism receipt over the enabled ruleset. |
| `updatedAt` | string or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `SecurityPresetsResponse` {#schema-securitypresetsresponse}

Every managed tier and safe preset this control plane offers.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `managedRulesets` | array of `ManagedRulesetBody` | yes | The three managed tiers. |
| `botPresets` | array of `BotPresetBody` | yes | The four bot presets. |
| `ratePresets` | array of `RatePresetBody` | yes | The four rate presets. |

### `SetManagedGroupRequest` {#schema-setmanagedgrouprequest}

Move one managed group off, or back onto, its catalog default.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | string | yes | off, log, challenge or block. |
| `reason` | string or null | no | Required for off and log, which remove protection. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Dry Run. |

### `SetManagedGroupResponse` {#schema-setmanagedgroupresponse}

The outcome of a managed-group change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `group` | `ManagedGroupBody` | yes | The group as it now stands. |
| `policyVersion` | integer | yes | The version after the change. |
| `enforcement` | `SlateSecurityEnforcementBody` | no | Enforcement. |

### `SetPresetsRequest` {#schema-setpresetsrequest}

Change a lane's managed tier and its bot, rate and challenge settings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `managedRuleset` | string | no | off, core or strict. |
| `botPreset` | string | no | Bot Preset. |
| `ratePreset` | string | no | Rate Preset. |
| `challengeMode` | string | no | Challenge Mode. |
| `overrides` | object | no | Overrides. |
| `managedOffReason` | string or null | no | Required when the managed ruleset is off. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `SetPresetsResponse` {#schema-setpresetsresponse}

The outcome of a preset change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `managedRuleset` | string | yes | The tier now in effect, or that would be. |
| `botPreset` | string | yes | The bot preset now in effect. |
| `ratePreset` | string | yes | The rate preset now in effect. |
| `policyVersion` | integer | yes | The version after the change. |
| `enforcement` | `SlateSecurityEnforcementBody` | no | Enforcement. |
| `warnings` | array of `SecurityWarningBody` | no | Warnings. |

### `SlateSecurityApprovalBody` {#schema-slatesecurityapprovalbody}

One recorded approval.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `subjectKind` | string | no | Subject Kind. |
| `subjectId` | string | no | Subject ID. |
| `digest` | string | no | Digest. |
| `authorActorName` | string | no | Author Actor Name. |
| `approverActorName` | string | no | Approver Actor Name. |
| `approvedAt` | string or null | no | Approved At. |
| `note` | string or null | no | Note. |

### `SlateSecurityApprovalRequest` {#schema-slatesecurityapprovalrequest}

Record a second person's approval of one exact body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjectKind` | enum `"rule"`, `"exception"`, `"policy"`, `"managed-group"` | yes | What is being approved. |
| `subjectId` | string | yes | Id of the subject. |
| `digest` | string | yes | The body that was reviewed, from the write response. |
| `authorActorKey` | string | yes | Immutable identity of whoever proposed it. |
| `authorActorName` | string | no | The proposer's display name. |
| `note` | string or null | no | Note. |

### `SlateSecurityAuditResponse` {#schema-slatesecurityauditresponse}

A lane's security audit trail.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entries` | array of `SlateSecurityAuditEntryBody` | yes | Most recent first. |

### `SlateSecurityDeleteRuleResponse` {#schema-slatesecuritydeleteruleresponse}

The outcome of a rule deletion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `SlateSecurityRevertRequest` {#schema-slatesecurityrevertrequest}

Restore a rule to a stored revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revision` | integer | yes | Which stored revision to apply. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Dry Run. |
| `reason` | string | no | Reason. |

### `SlateSecurityRevisionsResponse` {#schema-slatesecurityrevisionsresponse}

A rule's revision history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisions` | array of `SlateSecurityRevisionBody` | yes | Newest first. |

### `SlateSecurityRolloutRequest` {#schema-slatesecurityrolloutrequest}

Advance or retreat a rule's staged rollout.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rolloutMode` | string | yes | simulate or enforce. |
| `rolloutPercent` | integer | yes | Share of traffic, 0 to 100. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Dry Run. |
| `reason` | string | no | Reason. |

### `SlateSecuritySimulateCommandBody` {#schema-slatesecuritysimulatecommandbody}

A simulation, optionally over a what-if ruleset.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `request` | `SlateSecuritySimulateRequestBody` | yes | The test request. |
| `rules` | array of `SecurityRuleBody` or null | no | What-if overlay. When absent, the lane's stored rules are used. |
| `persist` | boolean | no | Record the outcome as a security event. |

### `SlateSecuritySimulateResponse` {#schema-slatesecuritysimulateresponse}

What the policy decides for a test request, and why every other rule did not.

``basis``, ``observed``, ``enforced`` and ``mitigated`` are literal defaults no handler
assigns. There is no code path able to make this response claim that a request was observed or
stopped, which is the structural form of the same guarantee V188 expresses as CHECKs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `action` | string | yes | allowed, logged, challenged, rate-limited or would-block. |
| `actionReason` | string | yes | One sentence naming the outcome and what produced it. |
| `winningRuleKind` | string | yes | What decided. |
| `winningRuleRef` | string or null | no | Winning Rule Ref. |
| `winningRuleLabel` | string | yes | Its name. |
| `rolloutMode` | string | yes | The rollout mode of whatever decided. |
| `exceptionApplied` | map of string or null | no | Exception Applied. |
| `considered` | array of `SlateSecuritySimulationStepBody` | yes | Every rule, and why it did not win. |
| `warnings` | array of `SecurityWarningBody` | no | Warnings. |
| `rulesDigest` | string | yes | Determinism receipt over the evaluated ruleset. |
| `policyVersion` | integer | yes | Which policy generation answered. |
| `basis` | `"policy-simulation"` | no | This is an evaluation of recorded policy against a test request, not a replay of an observed request. When a delivery tier lands, 'edge-observed' becomes the second value of this field rather than a change of meaning for the first. |
| `observed` | boolean | no | False: no delivery tier reported this request. |
| `enforced` | `false` | no | False: nothing acted on this request. |
| `mitigated` | `false` | no | False: nothing was stopped, because nothing can be. |
| `sentence` | string | no | What all of that means, in words. |
| `eventId` | string or null | no | Set when the outcome was recorded. |

### `SlateSecurityWriteRuleRequest` {#schema-slatesecuritywriterulerequest}

Create or replace a custom security rule.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string or null | no | Rule id, absent before it is written. |
| `ordinal` | integer | no | Precedence; lower wins. |
| `enabled` | boolean | no | Whether the rule participates. |
| `label` | string | no | Operator-facing rule name. |
| `matcherKind` | string | no | exact, prefix, glob or regex. |
| `matcherValue` | string | no | The route pattern. |
| `matcherMethods` | array of string | no | Matcher Methods. |
| `matcherHosts` | array of string | no | Matcher Hosts. |
| `conditions` | array of object | no | Conditions. |
| `action` | string | no | allow, log, challenge, rate-limit or block. |
| `rateRequests` | integer or null | no | Rate Requests. |
| `rateWindowSeconds` | integer or null | no | Rate Window Seconds. |
| `rolloutMode` | string | no | simulate or enforce. |
| `rolloutPercent` | integer | no | Rollout Percent. |
| `expiresAt` | string or null | no | Expires At. |
| `acknowledgedWarnings` | array of string | no | Acknowledged Warnings. |
| `bodyDigest` | string | no | Content digest of the decisive fields; what an approval names. |
| `revision` | integer | no | Monotonic revision counter. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `SlateSecurityWriteRuleResponse` {#schema-slatesecuritywriteruleresponse}

The outcome of a rule write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `rule` | `SecurityRuleBody` or null | no | Rule. |
| `bodyDigest` | string | yes | What an approval of this body must name. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateSecurityEnforcementBody` | no | Enforcement. |
| `warnings` | array of `SecurityWarningBody` | no | Warnings. |
