---
title: "Schema validation"
description: "REST endpoints tagged schema-validation: 3 operations."
sidebar_position: 56
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `schema-validation` · 3 operations

## `POST /v1/tenants/{tenant_slug}/schemas/{schema_ref}/synthesize` {#synthesize-payloads-for-schema-v1-tenants-tenant-slug-schemas-schema-ref-synthesize-post}

**Generate sample payloads — valid instances and single-constraint mutants**

Generate test payloads for any schema Apiome holds (IXH-5.2): a minimal valid instance, a full valid instance, one instance per polymorphic branch, and a set of mutants that each violate exactly one constraint. Nothing is persisted.

**Addressing** is identical to the validate endpoint — ``schema_ref`` is a path-shaped reference naming a Project revision (``project/{project_slug}/{version}[/{type}]``), a Catalog revision (``catalog/{item}/{version}[/{type}]``), or a type-registry type (``registry/{namespace}/{name}``) — so a payload can be generated and then validated against the very same reference.

**Everything returned is synthetic.** The response, every instance, and every value's provenance carry an explicit label. These payloads were generated from the schema; they are not real data and must never be presented as a captured example.

**Generation is deterministic.** The same schema and ``seed`` produce byte-identical payloads, so a generated fixture can be committed and re-derived. Values come from the schema's own ``const``, ``examples``, ``default``, or ``enum`` before anything is invented, and each value's ``provenance`` records which.

**Mutants are verified, not assumed.** Each one must provoke exactly one violation, of exactly the constraint it targets; candidates that fail for the wrong reason (or do not fail at all) are dropped and counted in ``rejected_mutants``. The available kinds are `required-missing`, `type-wrong`, `enum-out-of-range`, `pattern-violated`, `bound-exceeded`, `additional-properties-injected`, and `discriminator-mismatched`.

**Recursion terminates.** Generation stops descending into optional structure at ``depth_limit`` and at any reference cycle, and says so in ``diagnostics`` rather than truncating silently. External ``$ref``s resolve only against this tenant's registry; no network fetch is ever performed.

A schema that cannot be generated from is **not** an HTTP error: the response is a 200 with ``ok: false`` and a stable intake-taxonomy ``error`` code plus remediation. Only addressing faults are HTTP errors — 400 for a malformed reference, 404 for one that names nothing visible, 422 for one that resolves to material no schema can be derived from.

Operation id: `synthesize_payloads_for_schema_v1_tenants__tenant_slug__schemas__schema_ref__synthesize_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_ref` | path | string | yes | Path parameter identifying the schema ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for generate sample payloads — valid instances and single-constraint mutants.

- `application/json` — [`SchemaSynthesisRequest`](#schema-schemasynthesisrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for generate sample payloads — valid instances and single-constraint mutants. | `application/json` [`SchemaSynthesisResponse`](#schema-schemasynthesisresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schemas/{schema_ref}/targets` {#list-targets-for-schema-ref-v1-tenants-tenant-slug-schemas-schema-ref-targets-get}

**List the schemas a revision offers as validation targets**

Enumerate everything one revision offers the Schema Test Bench (IXH-5.3): its named types and the operation request/response bodies that resolve to a named type, each addressable by appending the type key to the same reference the validate (IXH-5.1) and synthesize (IXH-5.2) endpoints take.

**Addressing.** ``schema_ref`` is the IXH-5.1 path-shaped reference *without* its trailing type segment — ``project/{project_slug}/{version}`` or ``catalog/{item}/{version}``; ``{version}`` is a version label, a revision id, or ``latest``. A ``registry/…`` reference is rejected with 400: a registry type is a single stored schema, already enumerated by the type-registry API.

**Determinism.** Types are sorted by key; operation bodies by operation key, role, then status code — two calls over the same revision are byte-identical.

**Honesty.** A body defined inline (no named type) cannot be addressed by the reference grammar; such bodies are counted in a diagnostic, never silently dropped and never invented. Nothing is persisted.

Only addressing faults are HTTP errors — 400 for a malformed, registry, or type-qualified reference, 404 for one that names nothing visible, 422 for one that resolves to material no canonical model can be rebuilt from.

Operation id: `list_targets_for_schema_ref_v1_tenants__tenant_slug__schemas__schema_ref__targets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_ref` | path | string | yes | Path parameter identifying the schema ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the schemas a revision offers as validation targets. | `application/json` [`SchemaTargetsResponse`](#schema-schematargetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schemas/{schema_ref}/validate` {#validate-instance-against-schema-v1-tenants-tenant-slug-schemas-schema-ref-validate-post}

**Validate a JSON or XML payload against a cataloged schema**

Answer 'does this payload satisfy this schema?' for any schema Apiome holds (IXH-5.1). Nothing is persisted.

**Addressing.** ``schema_ref`` is a path-shaped reference naming one of three sources:

* ``project/{project_slug}/{version}[/{type}]`` — a publishable Project's revision;
* ``catalog/{item}/{version}[/{type}]`` — a Catalog item's revision, by slug or id;
* ``registry/{namespace}/{name}`` — a type-registry type, addressed by the same path a relative ``$ref`` inside the registry would use.

``{version}`` is a source-declared version label (``1.0.0``), a revision id, or ``latest``. ``{type}`` names one canonical type by its stable key (``acme.Pet``) or its source name (``Pet``); omit it to address the whole revision, which XML validation needs and which JSON validation accepts when the revision defines exactly one type.

**Findings** carry the JSON Pointer into the instance, the failing keyword, what the schema expected, what the instance actually held, a human-readable message, and the JSON Pointer into the schema. Order is deterministic — instance pointer (array indices numerically), then schema pointer, keyword, message — so two runs over the same input are byte-identical and reports diff cleanly across revisions.

**``valid`` is never guessed.** It is ``true`` only when a validator ran and found nothing, ``false`` only when a validator ran and found something, and ``null`` whenever no validator ran — for instance on a deployment without the XML toolchain, which reports ``validated: false`` with an ``ADAPTER_UNAVAILABLE`` diagnostic rather than passing an unchecked payload.

**Bounds.** ``$ref`` resolution is depth- and fan-out-bounded and cycle-safe, and resolves only against this tenant's registry — validation performs no network fetch, and a reference that cannot be resolved is reported as a diagnostic, never ignored. The instance is bounded by the import resource guards (size, alias expansion, nesting depth); XML documents additionally pass the hardened XML parser, so no DTD, entity, or external reference is ever expanded.

A payload that cannot be checked is **not** an HTTP error: the response is a 200 with ``ok: false`` and a stable intake-taxonomy ``error`` code plus remediation. Only addressing faults are HTTP errors — 400 for a malformed reference, 404 for one that names nothing visible, 422 for one that resolves to material no schema can be derived from.

Operation id: `validate_instance_against_schema_v1_tenants__tenant_slug__schemas__schema_ref__validate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_ref` | path | string | yes | Path parameter identifying the schema ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for validate a json or xml payload against a cataloged schema.

- `application/json` — [`SchemaInstanceValidationRequest`](#schema-schemainstancevalidationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for validate a json or xml payload against a cataloged schema. | `application/json` [`SchemaInstanceValidationResponse`](#schema-schemainstancevalidationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SchemaInstanceValidationRequest` {#schema-schemainstancevalidationrequest}

A payload to check against the schema named in the URL.

Exactly one of ``instance`` and ``instance_text`` must be supplied. ``instance`` is the
convenient form for a JSON payload a caller already holds as a value; ``instance_text`` is
the exact-bytes form, and the only form an XML payload can take.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `instance` | any or null | no | The payload as an already-parsed JSON value. Mutually exclusive with ``instance_text``. Sending an explicit ``null`` here validates the JSON value ``null``, which is a legitimate instance. |
| `instance_text` | string or null | no | The payload as raw text — JSON or XML, per ``media_type``. Mutually exclusive with ``instance``, and required for XML. |
| `media_type` | enum `"application/json"`, `"application/xml"` | no | How ``instance_text`` should be read. XML requires ``instance_text``. |
| `max_findings` | integer | no | Cap on returned findings; the true total is always reported separately. |
| `assert_formats` | boolean | no | Assert JSON Schema ``format`` rather than treating it as an annotation. Off by default: ``format`` is an annotation in every modern draft, and checkers whose optional dependency is absent are skipped silently, so an asserted-format pass is weaker evidence than a keyword pass. |

### `SchemaInstanceValidationResponse` {#schema-schemainstancevalidationresponse}

The verdict on one payload.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the request was serviceable at all. |
| `valid` | boolean or null | no | ``true`` when a validator ran and found nothing, ``false`` when it ran and found something, ``null`` when no validator ran — never a stand-in for a pass. |
| `validated` | boolean | yes | Whether a validator actually executed over the instance. |
| `validator` | string or null | no | Which validator ran (``jsonschema/2020-12``, ``xmllint.validate``). |
| `schema_ref` | string | yes | The schema reference exactly as it was requested. |
| `media_type` | string | yes | How the instance was read. |
| `source` | `SchemaSourceInfo` or null | no | What the reference resolved to. |
| `findings` | array of `InstanceFinding` | no | Ways the instance failed the schema, in a deterministic order: by instance pointer (array indices numerically), then schema pointer, keyword, and message. |
| `total_findings` | integer | no | How many findings existed before ``max_findings`` truncation. |
| `truncated` | boolean | no | Whether ``findings`` was cut short by ``max_findings``. |
| `diagnostics` | array of `ValidationDiagnostic` | no | Conditions that limited the check — an unresolvable ``$ref``, a bound that tripped, a source scalar with no JSON Schema equivalent, a missing toolchain. Never failures of the instance itself. |
| `error` | `SpecImportJobError` or null | no | Populated when ``ok`` is false: stable taxonomy code plus remediation. |

### `SchemaSynthesisRequest` {#schema-schemasynthesisrequest}

What to generate for the schema named in the URL.

Every field has a usable default: an empty body generates the whole set — minimal, full,
every branch, and the mutants — under seed 0.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `seed` | integer | no | Seed for the value generator. The same schema and seed always produce byte-identical payloads; change it to get a different sample of the same shapes. |
| `include_minimal` | boolean | no | Generate the required-properties-only instance. |
| `include_full` | boolean | no | Generate the every-optional-property instance. |
| `include_branches` | boolean | no | Generate one instance per `oneOf`/`anyOf` alternative and per `if`/`then`/`else` arm. Alternatives that produce a payload already returned are skipped. |
| `include_mutants` | boolean | no | Generate payloads that each violate exactly one constraint. Only mutants that provoke a single violation of the constraint they target are returned. |
| `mutation_kinds` | array of string or null | no | Restrict mutants to these kinds. Omit for all of them. Known kinds: `required-missing`, `type-wrong`, `enum-out-of-range`, `pattern-violated`, `bound-exceeded`, `additional-properties-injected`, `discriminator-mismatched`. |
| `max_mutants` | integer | no | Cap on returned mutants. Selection is round-robin across the mutation kinds, so a low cap still covers every kind the schema affords. |
| `max_branch_instances` | integer | no | Cap on returned branch instances. |
| `verify` | boolean | no | Validate every generated payload back against the schema, and drop any mutant that does not break exactly the constraint it targets. Turning this off returns the payloads unchecked, with `valid` null on every one of them. |

### `SchemaSynthesisResponse` {#schema-schemasynthesisresponse}

The generated payloads for one schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the request was serviceable at all. |
| `synthetic` | boolean | no | Always true. Every payload in this response was generated from the schema and is not, and never was, real data. |
| `notice` | string | no | Human-readable statement of the above, for display next to the payloads. |
| `schema_ref` | string | yes | The schema reference exactly as it was requested. |
| `seed` | integer | no | The seed used, echoed so a run can be reproduced. |
| `dialect` | string or null | no | The JSON Schema dialect the schema was read under. |
| `depth_limit` | integer | no | Nesting depth at which generation stops descending into optional structure. A recursive schema terminates here; the omission is reported as a diagnostic. |
| `verified` | boolean | no | Whether generated payloads were validated back. |
| `source` | `SchemaSourceInfo` or null | no | What the reference resolved to. |
| `instances` | array of `SynthesizedInstance` | no | The generated payloads, ordered minimal, full, branches, then mutants. Each carries its own `synthetic` label, what it is for, whether it is meant to be valid, and — for a mutant — the single constraint it breaks. |
| `counts` | map of integer | no | How many instances of each kind were returned (`minimal`, `full`, …). |
| `rejected_mutants` | integer | no | Mutation candidates dropped because they did not fail the schema with exactly the constraint they targeted — a negative test that fails for the wrong reason is worse than no test. |
| `truncated` | boolean | no | Whether `max_mutants` or `max_branch_instances` cut the set short. |
| `diagnostics` | array of `ValidationDiagnostic` | no | Conditions that limited generation — a construct with no generatable value, an unresolvable `$ref`, a recursion bound, an authored example that does not satisfy its own schema. Never a fault of the request. |
| `error` | `SpecImportJobError` or null | no | Populated when `ok` is false: stable taxonomy code plus remediation. |

### `SchemaTargetsResponse` {#schema-schematargetsresponse}

Everything one revision offers the Test Bench to validate against.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Always ``true``: a resolvable revision always enumerates. |
| `schema_ref` | string | yes | The reference exactly as it was requested. |
| `source` | `SchemaSourceInfo` | yes | What the reference resolved to. |
| `types` | array of `SchemaTargetType` | no | Named types, sorted by key. |
| `operation_bodies` | array of `SchemaOperationBodyTarget` | no | Request/response bodies that resolve to a named type, sorted by operation key, role, then status code. |
| `xml_document` | boolean | no | Whether the revision is backed by an XML grammar, so the bare (type-less) reference validates whole XML documents. |
| `diagnostics` | array of `ValidationDiagnostic` | no | Conditions that limited the listing — e.g. bodies defined inline rather than as named types, which the reference grammar cannot address. Never an error. |
