---
title: "Slate functions"
description: "REST endpoints tagged slate-functions: 27 operations."
sidebar_position: 63
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-functions` · 27 operations

## `GET /v1/slate/environments/{environment_id}/functions` {#get-function-policy-v1-slate-environments-environment-id-functions-get}

**Get Function Policy**

Return a lane's function policy, every function with its privileges, and what it runs.

Operation id: `get_function_policy_v1_slate_environments__environment_id__functions_get`

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
| 200 | Successful response for get function policy. | `application/json` [`FunctionPolicyResponse`](#schema-functionpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions` {#create-function-v1-slate-environments-environment-id-functions-post}

**Create Function**

Create a function, refusing an unsafe one by name.

Operation id: `create_function_v1_slate_environments__environment_id__functions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create function.

- `application/json` — [`WriteFunctionRequest`](#schema-writefunctionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create function. | `application/json` [`WriteFunctionResponse`](#schema-writefunctionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/approvals` {#record-function-approval-v1-slate-environments-environment-id-functions-approvals-post}

**Record Function Approval**

Record the approving half of dual control.

The approver is always the *authenticated caller* — there is no field by which one person can
record somebody else's approval, which is the only version of two-person review that means
anything. Approving one's own change is refused here as ``approval-self`` and again by V189's
``CHECK (approver_actor_key <> author_actor_key)``.

Operation id: `record_function_approval_v1_slate_environments__environment_id__functions_approvals_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record function approval.

- `application/json` — [`SlateFunctionsApprovalRequest`](#schema-slatefunctionsapprovalrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record function approval. | `application/json` [`SlateFunctionsApprovalBody`](#schema-slatefunctionsapprovalbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/functions/audit` {#get-function-audit-v1-slate-environments-environment-id-functions-audit-get}

**Get Function Audit**

Return a lane's append-only function audit trail, most recent first.

Operation id: `get_function_audit_v1_slate_environments__environment_id__functions_audit_get`

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
| 200 | Successful response for get function audit. | `application/json` [`SlateFunctionsAuditResponse`](#schema-slatefunctionsauditresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/functions/audit/export` {#export-function-audit-v1-slate-environments-environment-id-functions-audit-export-get}

**Export Function Audit**

Export a lane's function audit trail as CSV.

VIEW rather than PUBLISH: §29.7 gives the Auditor read-only policy and exportable audit, and an
export gated behind the permission to *change* functions would be an export the auditor cannot
run.

Modelled on ``access_routes.py``'s exporter, and fixing the two defects that precedent carries.

**CSV injection is neutralized.** A cell whose first character is ``=``, ``+``, ``-``, ``@``, a
tab or a carriage return is prefixed with an apostrophe. An actor display name and a refusal
detail are attacker-influenced text, and the existing exporter writes them raw, so opening the
evidence in a spreadsheet is a code-execution path.

**Nothing is silently truncated.** The existing exporter caps at 1000 rows with no signal,
which in compliance evidence is a correctness bug rather than a performance choice: an auditor
reading a truncated ledger concludes the missing entries never happened. This one reads one row
past the cap, and when there are more it emits a final row saying so in words.

Reading the evidence is itself audit-worthy — who exported the record of who let a function
read secrets is part of that record — so an ``export`` audit row is written before the download
begins.

Operation id: `export_function_audit_v1_slate_environments__environment_id__functions_audit_export_get`

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
| 200 | Successful response for export function audit. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/functions/invocations` {#get-function-invocations-v1-slate-environments-environment-id-functions-invocations-get}

**Get Function Invocations**

Return a lane's invocation records, most recent first.

The filter names are the designer's dimension ids unchanged, so filtering on screen and
filtering in a query cannot mean different things. ``variantRef`` is how "which function served
this customer" gets narrowed down.

Operation id: `get_function_invocations_v1_slate_environments__environment_id__functions_invocations_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `functionRef` | query | string or null | no | Query parameter: function ref. |
| `outcome` | query | string or null | no | Query parameter: outcome. |
| `route` | query | string or null | no | Query parameter: route. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `variantRef` | query | string or null | no | Query parameter: variant ref. |
| `source` | query | string or null | no | Source material descriptor (file, URL, paste, or discovery). |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function invocations. | `application/json` [`InvocationsResponse`](#schema-invocationsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/functions/invocations/{invocation_id}` {#get-function-invocation-v1-slate-environments-environment-id-functions-invocations-invocation-id-get}

**Get Function Invocation**

Return one invocation record with its redacted evidence.

Operation id: `get_function_invocation_v1_slate_environments__environment_id__functions_invocations__invocation_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `invocation_id` | path | string | yes | Path parameter identifying the invocation id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function invocation. | `application/json` [`InvocationBody`](#schema-invocationbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/policy` {#set-function-policy-v1-slate-environments-environment-id-functions-policy-put}

**Set Function Policy**

Change a lane's function policy: whether functions run, where, and within what ceilings.

Loosening residency to ``unrestricted`` with no stated reason is refused here with a sentence,
and again by V189's CHECK. Both are deliberate: the operator should meet the explanation, not
a constraint violation, and no future code path should be able to skip the explanation.

Operation id: `set_function_policy_v1_slate_environments__environment_id__functions_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set function policy.

- `application/json` — [`SetFunctionPolicyRequest`](#schema-setfunctionpolicyrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set function policy. | `application/json` [`SetFunctionPolicyResponse`](#schema-setfunctionpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/simulate` {#simulate-function-invocation-v1-slate-environments-environment-id-functions-simulate-post}

**Simulate Function Invocation**

Explain what this lane's policy decides for a test request, and why every function lost.

A read, not a write, unless ``persist`` is set — and VIEW rather than PUBLISH deliberately.
"Which function served this customer", or "why did my function not run", is the question that
brings an operator here during an incident, so requiring PUBLISH would put the answer out of
reach of exactly the person asking.

Operation id: `simulate_function_invocation_v1_slate_environments__environment_id__functions_simulate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for simulate function invocation.

- `application/json` — [`SlateFunctionsSimulateCommandBody`](#schema-slatefunctionssimulatecommandbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for simulate function invocation. | `application/json` [`SlateFunctionsSimulateResponse`](#schema-slatefunctionssimulateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/variants` {#create-variant-v1-slate-environments-environment-id-functions-variants-post}

**Create Variant**

Create a personalization variant, refusing an unsafe one by name.

Operation id: `create_variant_v1_slate_environments__environment_id__functions_variants_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create variant.

- `application/json` — [`WriteVariantRequest`](#schema-writevariantrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create variant. | `application/json` [`WriteVariantResponse`](#schema-writevariantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/variants/{variant_id}` {#replace-variant-v1-slate-environments-environment-id-functions-variants-variant-id-put}

**Replace Variant**

Replace a personalization variant, running the same gates as a create.

Operation id: `replace_variant_v1_slate_environments__environment_id__functions_variants__variant_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `variant_id` | path | string | yes | Path parameter identifying the variant id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace variant.

- `application/json` — [`WriteVariantRequest`](#schema-writevariantrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace variant. | `application/json` [`WriteVariantResponse`](#schema-writevariantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/functions/variants/{variant_id}` {#remove-variant-v1-slate-environments-environment-id-functions-variants-variant-id-delete}

**Remove Variant**

Remove a personalization variant.

Operation id: `remove_variant_v1_slate_environments__environment_id__functions_variants__variant_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `variant_id` | path | string | yes | Path parameter identifying the variant id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove variant. | `application/json` [`DeleteVariantResponse`](#schema-deletevariantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/{function_id}` {#replace-function-v1-slate-environments-environment-id-functions-function-id-put}

**Replace Function**

Replace a function, running the same gates as a create.

Operation id: `replace_function_v1_slate_environments__environment_id__functions__function_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace function.

- `application/json` — [`WriteFunctionRequest`](#schema-writefunctionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace function. | `application/json` [`WriteFunctionResponse`](#schema-writefunctionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/functions/{function_id}` {#remove-function-v1-slate-environments-environment-id-functions-function-id-delete}

**Remove Function**

Remove a function, keeping its body so the removal can be undone.

Operation id: `remove_function_v1_slate_environments__environment_id__functions__function_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove function. | `application/json` [`DeleteFunctionResponse`](#schema-deletefunctionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/{function_id}/capabilities` {#grant-function-capability-v1-slate-environments-environment-id-functions-function-id-capabilities-put}

**Grant Function Capability**

Grant one runtime capability to a function.

Writing the row *is* the grant; there is no ``granted`` boolean to set. A grant with no stated
reason is refused as ``capability-without-reason``, and a grant of a standing privilege with no
end date — or one so distant it is permanent in practice — as ``capability-unbounded``.

Operation id: `grant_function_capability_v1_slate_environments__environment_id__functions__function_id__capabilities_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for grant function capability.

- `application/json` — [`GrantCapabilityRequest`](#schema-grantcapabilityrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for grant function capability. | `application/json` [`CapabilityGrantResponse`](#schema-capabilitygrantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/functions/{function_id}/capabilities/{capability}` {#revoke-function-capability-v1-slate-environments-environment-id-functions-function-id-capabilities-capability-delete}

**Revoke Function Capability**

Revoke one capability by deleting its grant row.

Deleting rather than flipping a flag is the whole design: the absence of a row is the denial,
so a revocation cannot half-succeed into a state that still permits something.

Operation id: `revoke_function_capability_v1_slate_environments__environment_id__functions__function_id__capabilities__capability__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `capability` | path | string | yes | Path parameter identifying the capability segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for revoke function capability. | `application/json` [`DeleteGrantResponse`](#schema-deletegrantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/{function_id}/egress` {#set-function-egress-rule-v1-slate-environments-environment-id-functions-function-id-egress-put}

**Set Function Egress Rule**

Allowlist one outbound destination for a function.

Deny-by-default in the same shape as a capability: the row is the allowance, and there is no
wildcard kind to write. An entry with no stated reason is refused, and an entry that does not
actually cover the destinations the caller says it is for is refused as ``egress-unapproved``
rather than written and discovered to be inert in production.

Operation id: `set_function_egress_rule_v1_slate_environments__environment_id__functions__function_id__egress_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set function egress rule.

- `application/json` — [`SetEgressRuleRequest`](#schema-setegressrulerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set function egress rule. | `application/json` [`EgressRuleResponse`](#schema-egressruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/functions/{function_id}/egress/{rule_id}` {#remove-function-egress-rule-v1-slate-environments-environment-id-functions-function-id-egress-rule-id-delete}

**Remove Function Egress Rule**

Withdraw an egress allowance by deleting its row.

Operation id: `remove_function_egress_rule_v1_slate_environments__environment_id__functions__function_id__egress__rule_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove function egress rule. | `application/json` [`DeleteGrantResponse`](#schema-deletegrantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/{function_id}/revert` {#revert-function-route-v1-slate-environments-environment-id-functions-function-id-revert-post}

**Revert Function Route**

Restore a function to a stored revision.

Reverting applies the recorded document rather than reconstructing intent from an audit
sentence, which is what makes §29.5's "every function change can be reverted" a fact about this
system rather than a claim about it.

Operation id: `revert_function_route_v1_slate_environments__environment_id__functions__function_id__revert_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for revert function route.

- `application/json` — [`SlateFunctionsRevertRequest`](#schema-slatefunctionsrevertrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for revert function route. | `application/json` [`WriteFunctionResponse`](#schema-writefunctionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/functions/{function_id}/revisions` {#get-function-revisions-v1-slate-environments-environment-id-functions-function-id-revisions-get}

**Get Function Revisions**

Return a function's revision history and its immutable versions, newest first.

Operation id: `get_function_revisions_v1_slate_environments__environment_id__functions__function_id__revisions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function revisions. | `application/json` [`SlateFunctionsRevisionsResponse`](#schema-slatefunctionsrevisionsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/{function_id}/rollout` {#set-function-rollout-v1-slate-environments-environment-id-functions-function-id-rollout-post}

**Set Function Rollout**

Advance or retreat a function's staged rollout.

This is where dual control actually bites. A function can be written in simulate freely; the
write that puts code into the request path runs the same
:func:`app.slate_functions.evaluate_function_safety` gate as a body edit, so it is refused as
``enforce-without-version``, ``enforce-without-simulation``, ``enforce-without-approval``,
``approval-stale`` or ``approval-self`` rather than succeeding because it happened to arrive by
a different route.

Operation id: `set_function_rollout_v1_slate_environments__environment_id__functions__function_id__rollout_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set function rollout.

- `application/json` — [`SlateFunctionsRolloutRequest`](#schema-slatefunctionsrolloutrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set function rollout. | `application/json` [`WriteFunctionResponse`](#schema-writefunctionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/functions/{function_id}/secrets` {#set-function-secret-ref-v1-slate-environments-environment-id-functions-function-id-secrets-put}

**Set Function Secret Ref**

Declare a secret reference on a function.

There is no value field on this request and no value column in the schema behind it, which is
§29.5's first flat prohibition made a schema impossibility rather than a validation. The half a
schema cannot express — that the reference stays inside this function's own boundary — is
refused here as ``secret-cross-project``, with no acknowledgement path, because a cross-project
reference is not a cost somebody may accept on their own authority.

Operation id: `set_function_secret_ref_v1_slate_environments__environment_id__functions__function_id__secrets_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set function secret ref.

- `application/json` — [`SetSecretRefRequest`](#schema-setsecretrefrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set function secret ref. | `application/json` [`SecretRefResponse`](#schema-secretrefresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/functions/{function_id}/secrets/{ref_id}` {#remove-function-secret-ref-v1-slate-environments-environment-id-functions-function-id-secrets-ref-id-delete}

**Remove Function Secret Ref**

Withdraw a secret reference.

Operation id: `remove_function_secret_ref_v1_slate_environments__environment_id__functions__function_id__secrets__ref_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `ref_id` | path | string | yes | Path parameter identifying the ref id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove function secret ref. | `application/json` [`DeleteGrantResponse`](#schema-deletegrantresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/functions/{function_id}/versions` {#add-function-version-v1-slate-environments-environment-id-functions-function-id-versions-post}

**Add Function Version**

Record a new immutable source version, optionally promoting it to live.

Versions are written once and never edited: promoting different code moves the function's
``activeVersionId`` rather than reshaping a stored artifact. Promoting is still a change to the
function, so the function's prior body is recorded as a ``version-added`` revision before the
pointer moves.

Operation id: `add_function_version_v1_slate_environments__environment_id__functions__function_id__versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `function_id` | path | string | yes | Path parameter identifying the function id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add function version.

- `application/json` — [`AddVersionRequest`](#schema-addversionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for add function version. | `application/json` [`AddVersionResponse`](#schema-addversionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/functions/capabilities` {#get-function-capabilities-v1-slate-functions-capabilities-get}

**Get Function Capabilities**

Return the runtime capability catalog, with what each grant opens and what it is unsafe for.

Deny-by-default is modelled as the absence of a row, so no table anywhere lists what the
capabilities are. This endpoint is that list — versioned in code and reviewable in a diff
rather than seeded per tenant — and it is the only way an operator can read what a grant costs
before making one.

Operation id: `get_function_capabilities_v1_slate_functions_capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function capabilities. | `application/json` [`CapabilitiesResponse`](#schema-capabilitiesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/functions/presets` {#get-function-presets-v1-slate-functions-presets-get}

**Get Function Presets**

Return the residency postures and cache-key effects as data.

§29.7 gives the Publisher safe presets and never a runtime, and a preset is its fields rather
than its name. A residency option that cannot say what it does *not* cover is one nobody can
honestly choose, which is why ``doesNotCover`` is a required field here rather than
documentation somewhere else.

Operation id: `get_function_presets_v1_slate_functions_presets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function presets. | `application/json` [`FunctionPresetsResponse`](#schema-functionpresetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/functions/runtimes` {#get-function-runtimes-v1-slate-functions-runtimes-get}

**Get Function Runtimes**

Return the execution runtime catalog.

Each runtime states what its sandbox contains and what escaping it would cost. A runtime that
cannot say that is a runtime nobody can safely choose.

Operation id: `get_function_runtimes_v1_slate_functions_runtimes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get function runtimes. | `application/json` [`RuntimesResponse`](#schema-runtimesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AddVersionRequest` {#schema-addversionrequest}

Record a new immutable source version, optionally promoting it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sourceDigest` | string | yes | Content address of the source. |
| `body` | object | no | The version manifest. |
| `runtime` | string | no | Runtime this version was built for. |
| `sourceBytes` | integer or null | no | Size in bytes, or null. |
| `sourceOrigin` | string | no | upload, build or import. |
| `sourceRef` | string or null | no | Commit, build id or upload ref. |
| `activate` | boolean | no | Whether to make this the live version. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `AddVersionResponse` {#schema-addversionresponse}

The outcome of adding a version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `version` | `FunctionVersionBody` or null | no | The version written. |
| `activated` | boolean | yes | Whether it was promoted to live. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateFunctionsEnforcementBody` | no | Enforcement. |

### `CapabilitiesResponse` {#schema-capabilitiesresponse}

The runtime capability catalog.

Deny-by-default is the absence of a grant row, so there is no table anywhere listing what the
capabilities are. This is that list, versioned in code rather than seeded per tenant, which is
the only way an operator can read what a grant opens before making one.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `capabilities` | array of `CapabilityBody` | yes | Every capability, safest first. |

### `CapabilityGrantResponse` {#schema-capabilitygrantresponse}

The outcome of a capability grant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `capability` | `CapabilityGrantBody` or null | no | The grant. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateFunctionsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |

### `DeleteFunctionResponse` {#schema-deletefunctionresponse}

The outcome of a function deletion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `DeleteGrantResponse` {#schema-deletegrantresponse}

The outcome of revoking a grant, an allowance or a reference.

Revoking is a DELETE, because the absence of a row is the denial. There is no field here
reporting a ``granted`` flag, because there is no such column to report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `DeleteVariantResponse` {#schema-deletevariantresponse}

The outcome of removing a variant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `EgressRuleResponse` {#schema-egressruleresponse}

The outcome of an egress allowlist write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `egress` | `EgressRuleBody` or null | no | The entry as written. |
| `policyVersion` | integer | yes | The version after the write. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |

### `FunctionPolicyResponse` {#schema-functionpolicyresponse}

A lane's complete function policy, and what it actually runs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | The lane. |
| `functionsEnabled` | boolean | yes | Whether functions may exist on this lane at all. |
| `policyVersion` | integer | yes | Optimistic-concurrency token. |
| `edgeAttached` | boolean | yes | Whether a runtime tier serves this lane. |
| `edgeProvider` | string or null | no | Its name, or null. |
| `defaultRegion` | string | yes | Where functions run by default. |
| `defaultResidencyClass` | string | yes | The lane's residency posture. |
| `defaultCpuMsLimit` | integer | yes | CPU ceiling a function may tighten. |
| `defaultMemoryMbLimit` | integer | yes | Memory ceiling a function may tighten. |
| `defaultWallMsLimit` | integer | yes | Wall-clock ceiling a function may tighten. |
| `residencyWaiverReason` | string or null | no | Why residency was loosened, when it was. |
| `enforcement` | `SlateFunctionsEnforcementBody` | no | Whether the policy runs anything. |
| `functions` | array of `FunctionBody` | yes | Functions, in precedence order. |
| `functionsDigest` | string | yes | Determinism receipt over the enabled function set. |
| `updatedAt` | string or null | no | When the policy last changed. |
| `updatedBy` | string or null | no | Who changed it. |

### `FunctionPresetsResponse` {#schema-functionpresetsresponse}

The safe presets a Publisher may choose between without ever touching a runtime.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `residencyClasses` | array of `SlateFunctionsResidencyClassBody` | yes | The three residency postures. |
| `cacheKeyEffects` | array of `CacheKeyEffectBody` | yes | The three cache-key effects. |

### `GrantCapabilityRequest` {#schema-grantcapabilityrequest}

Grant one runtime capability to a function.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `capability` | string | yes | Which capability, from the catalog. |
| `reason` | string | yes | Why the function needs it. |
| `expiresAt` | string or null | no | When the grant lapses. Required for the standing privileges. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `InvocationBody` {#schema-invocationbody}

One invocation record, with its redacted evidence.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Invocation id. |
| `at` | string or null | no | When it was recorded. |
| `source` | string | no | policy-simulation or edge-observed. |
| `functionRef` | string | no | The function that decided. |
| `functionLabel` | string | no | Its label as it read at the time. |
| `route` | string | no | The request path. |
| `method` | string | no | The request method. |
| `releaseId` | string or null | no | Release active at the time. |
| `region` | string or null | no | Region, when known. |
| `variantRef` | string or null | no | Variant selected, when one was. |
| `outcome` | string | no | What the evaluation concluded. |
| `executed` | boolean | no | Whether code actually ran. |
| `edgeAttached` | boolean | no | Whether a runtime tier was attached. |
| `cpuMs` | integer or null | no | CPU consumed, or null. |
| `wallMs` | integer or null | no | Wall-clock elapsed, or null. |
| `memoryPeakMb` | integer or null | no | Peak memory, or null. |
| `denialReason` | string or null | no | Why a denial happened. |
| `evidence` | map of string | no | Redacted request evidence. |
| `retainUntil` | string or null | no | When the evidence is purged. |

### `InvocationsResponse` {#schema-invocationsresponse}

A lane's invocation records.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `invocations` | array of [`InvocationBody`](#schema-invocationbody) | yes | Most recent first. |
| `observed` | boolean | no | False: none of these were observed in a request path. |
| `sentence` | string | no | What that means. |
| `runtimeSentence` | string | no | Why there are no resource measurements. |

### `RuntimesResponse` {#schema-runtimesresponse}

The execution runtime catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runtimes` | array of `RuntimeBody` | yes | Every runtime, narrowest sandbox first. |

### `SecretRefResponse` {#schema-secretrefresponse}

The outcome of declaring a secret reference.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `secret` | `SecretRefBody` or null | no | The reference as written. |
| `policyVersion` | integer | yes | The version after the write. |

### `SetEgressRuleRequest` {#schema-setegressrulerequest}

Allowlist one outbound destination for a function.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `destinationKind` | string | no | exact-host or host-suffix. |
| `destination` | string | yes | The host or host suffix. |
| `scheme` | string | no | https or http. |
| `port` | integer or null | no | Permitted port, or null for default. |
| `methods` | array of string | no | Methods; empty means every one. |
| `reason` | string | yes | Why this destination is reachable. |
| `expiresAt` | string or null | no | When it lapses, or null. |
| `destinations` | array of string | no | Destinations this entry is meant to cover, checked here. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |

### `SetFunctionPolicyRequest` {#schema-setfunctionpolicyrequest}

Change a lane's function policy: whether functions run, where, and within what ceilings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `functionsEnabled` | boolean | no | Whether functions may exist here. |
| `defaultRegion` | string | no | Where functions run by default. |
| `defaultResidencyClass` | string | no | in-region-only, region-pinned or unrestricted. |
| `defaultCpuMsLimit` | integer | no | CPU ceiling in milliseconds. |
| `defaultMemoryMbLimit` | integer | no | Memory ceiling in MB. |
| `defaultWallMsLimit` | integer | no | Wall-clock ceiling in ms. |
| `residencyWaiverReason` | string or null | no | Required when residency is unrestricted. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `SetFunctionPolicyResponse` {#schema-setfunctionpolicyresponse}

The outcome of a function policy change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `functionsEnabled` | boolean | yes | Whether functions may exist, after the change. |
| `defaultResidencyClass` | string | yes | The residency posture now in effect. |
| `policyVersion` | integer | yes | The version after the change. |
| `enforcement` | `SlateFunctionsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |

### `SetSecretRefRequest` {#schema-setsecretrefrequest}

Declare a secret reference on a function. There is no value field, by construction.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `secretName` | string | yes | Name of the secret in the vault that holds the material. |
| `alias` | string | yes | Identifier the function code binds to. |
| `scope` | string | no | function or environment. |
| `ownerTenantId` | string | no | Tenant the secret belongs to. A differing value is refused. |
| `ownerEnvironmentId` | string | no | Environment the secret belongs to. A differing value is refused. |
| `ownerFunctionId` | string | no | Function the secret belongs to, for a function-scoped reference. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |

### `SlateFunctionsApprovalBody` {#schema-slatefunctionsapprovalbody}

One recorded approval.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Approval id. |
| `subjectKind` | string | no | What was approved. |
| `subjectId` | string | no | Id of the subject. |
| `digest` | string | no | The body that was reviewed. |
| `authorActorName` | string | no | Who proposed it. |
| `approverActorName` | string | no | Who approved it. |
| `approvedAt` | string or null | no | When. |
| `note` | string or null | no | Reviewer note, when there is one. |

### `SlateFunctionsApprovalRequest` {#schema-slatefunctionsapprovalrequest}

Record a second person's approval of one exact body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjectKind` | enum `"policy"`, `"function"`, `"version"`, `"capability"`, `"egress-rule"`, `"variant"` | yes | What is being approved. |
| `subjectId` | string | yes | Id of the subject. |
| `digest` | string | yes | The body that was reviewed, from the write response. |
| `authorActorKey` | string | yes | Immutable identity of whoever proposed it. |
| `authorActorName` | string | no | The proposer's display name. |
| `note` | string or null | no | Optional reviewer note. |

### `SlateFunctionsAuditResponse` {#schema-slatefunctionsauditresponse}

A lane's function audit trail.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entries` | array of `SlateFunctionsAuditEntryBody` | yes | Most recent first. |

### `SlateFunctionsRevertRequest` {#schema-slatefunctionsrevertrequest}

Restore a function to a stored revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revision` | integer | yes | Which stored revision to apply. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `SlateFunctionsRevisionsResponse` {#schema-slatefunctionsrevisionsresponse}

A function's revision history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisions` | array of `SlateFunctionsRevisionBody` | yes | Newest first. |
| `versions` | array of `FunctionVersionBody` | no | The immutable versions alongside them. |

### `SlateFunctionsRolloutRequest` {#schema-slatefunctionsrolloutrequest}

Advance or retreat a function's staged rollout.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rolloutMode` | string | yes | simulate or enforce. |
| `rolloutPercent` | integer | yes | Share of traffic, 0 to 100. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `SlateFunctionsSimulateCommandBody` {#schema-slatefunctionssimulatecommandbody}

A simulation, optionally over a what-if function set.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `request` | `SlateFunctionsSimulateRequestBody` | yes | The test request. |
| `functions` | array of `FunctionBody` or null | no | What-if overlay. When absent, the lane's stored functions are used. |
| `persist` | boolean | no | Record the outcome as an invocation. |

### `SlateFunctionsSimulateResponse` {#schema-slatefunctionssimulateresponse}

What the policy decides for a test request, and why every other function did not.

``basis``, ``observed``, ``executed`` and ``enforced`` are literal defaults no handler
assigns. There is no code path able to make this response claim that a request was observed or
that code ran, which is the structural form of the same guarantee V189 expresses as CHECKs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `outcome` | string | yes | What the policy concluded. Never 'ran'. |
| `outcomeReason` | string | yes | One sentence naming the outcome and what produced it. |
| `functionRef` | string or null | no | The function that won. |
| `functionLabel` | string | yes | Its name. |
| `versionRef` | string or null | no | The version that would have run. |
| `runtime` | string | yes | The runtime it declares. |
| `rolloutMode` | string | yes | Its rollout mode. |
| `rolloutPercent` | integer | yes | Its rollout percentage. |
| `region` | string | yes | Where it would have run. |
| `residencyClass` | string | yes | The residency posture it would have run under. |
| `limits` | map of integer | no | The ceilings it runs within. |
| `variantRef` | string or null | no | The variant selected. |
| `variantLabel` | string | yes | Its name. |
| `fallbackVariant` | string | yes | What every unmatched reader receives. |
| `cacheKeyEffect` | string | yes | The resolved effect on the shared cache key. |
| `privacyClass` | string | yes | The privacy classification of the selected variant. |
| `consentBasis` | string | yes | Its consent basis. |
| `analyticsDimension` | string | yes | The dimension it reports under. |
| `capabilitiesGranted` | array of string | no | Held and used. |
| `capabilitiesDenied` | array of string | no | Asked for and not held. Deny-by-default surfaces here. |
| `egressAllowed` | array of string | no | Destinations covered. |
| `egressDenied` | array of string | no | Destinations not covered. |
| `denialReason` | string or null | no | Why a denial happened. |
| `considered` | array of `SlateFunctionsSimulationStepBody` | yes | Every function and variant, and why it did not win. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |
| `functionsDigest` | string | yes | Determinism receipt over the evaluated function set. |
| `policyVersion` | integer | yes | Which policy generation answered. |
| `basis` | `"policy-simulation"` | no | This is an evaluation of recorded policy against a test request, not a replay of an observed request. When a runtime tier lands, 'edge-observed' becomes the second value of this field rather than a change of meaning for the first. |
| `observed` | boolean | no | False: no runtime tier reported this request. |
| `executed` | `false` | no | False: no code ran, because there is nothing to run it in. |
| `enforced` | `false` | no | False: nothing acted on this request. |
| `sentence` | string | no | What all of that means, in words. |
| `runtimeSentence` | string | no | Why there are no resource measurements. |
| `invocationId` | string or null | no | Set when the outcome was recorded. |

### `WriteFunctionRequest` {#schema-writefunctionrequest}

Create or replace a function.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string or null | no | Function id, absent before it is written. |
| `ordinal` | integer | no | Precedence; lower wins. |
| `enabled` | boolean | no | Whether the function participates. |
| `label` | string | no | Operator-facing function name. |
| `matcherKind` | string | no | exact, prefix, glob or regex. |
| `matcherValue` | string | no | The route pattern. |
| `matcherMethods` | array of string | no | Methods; empty is all. |
| `matcherHosts` | array of string | no | Hosts; empty is all. |
| `runtime` | string | no | js-isolate or wasm. |
| `activeVersionId` | string or null | no | The live version, or null. |
| `rolloutMode` | string | no | simulate or enforce. |
| `rolloutPercent` | integer | no | Share of traffic, 0 to 100. |
| `region` | string or null | no | Region override, or null to inherit. |
| `residencyClass` | string or null | no | Residency override, or null to inherit. |
| `cpuMsLimit` | integer or null | no | CPU override, or null. |
| `memoryMbLimit` | integer or null | no | Memory override, or null. |
| `wallMsLimit` | integer or null | no | Wall-clock override, or null. |
| `envVarNames` | array of string | no | Non-secret environment variable names. Names only. |
| `declaredDestinations` | array of string | no | Hosts the version manifest says the code will call. |
| `acknowledgedWarnings` | array of string | no | Warning reasons the operator accepted. |
| `bodyDigest` | string | no | Content digest of the decisive fields; what an approval names. |
| `revision` | integer | no | Monotonic revision counter. |
| `capabilities` | array of `CapabilityGrantBody` | no | Live capability grants. Absence of one is a denial. |
| `egress` | array of `EgressRuleBody` | no | Egress allowlist entries. Absence of one is a denial. |
| `secrets` | array of `SecretRefBody` | no | Secret references. References only, never values. |
| `variants` | array of `VariantBody` | no | Personalization variants, in selection order. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteFunctionResponse` {#schema-writefunctionresponse}

The outcome of a function write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `function` | `FunctionBody` or null | no | The function as written. |
| `bodyDigest` | string | yes | What an approval of this body must name. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateFunctionsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |

### `WriteVariantRequest` {#schema-writevariantrequest}

Create or replace a personalization variant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string or null | no | Variant id, absent before it is written. |
| `functionId` | string | no | Function that selects between variants. |
| `ordinal` | integer | no | Precedence among variants; lower wins. |
| `enabled` | boolean | no | Whether the variant participates. |
| `label` | string | no | Operator-facing name. |
| `audienceKind` | string | no | geo, language, device, cohort or experiment. |
| `audienceMatcher` | array of object | no | The audience predicates. |
| `fallbackVariant` | string | no | What every reader the audience rule does not match receives. |
| `cacheKeyEffect` | string | no | none, vary-on-dimension or bypass-cache. |
| `varyDimension` | string | no | What the cache key varies on. |
| `analyticsDimension` | string | no | The dimension it reports under. |
| `privacyClass` | string | no | non-personal, pseudonymous or personal. |
| `consentBasis` | string | no | not-required, explicit-consent or legitimate-interest. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteVariantResponse` {#schema-writevariantresponse}

The outcome of a variant write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `variant` | `VariantBody` or null | no | The variant as written. |
| `policyVersion` | integer | yes | The version after the write. |
| `warnings` | array of `FunctionWarningBody` | no | Warnings. |
