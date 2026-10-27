---
title: "Built-in lint rules"
description: "Every built-in lint rule: stable id, default severity and rationale."
sidebar_position: 7
tags: [lint, reference]
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Reference for every built-in lint rule in the rule-catalog registry (GOV-1.2). Each rule's
**id is stable** — it is exactly the string lint findings carry in their `rule` field, so a
violation always links back to the rule documented here. The **default severity** is what the
rule applies when no style guide overrides it.

Blocking (`error`) rules additionally publish reference, remediation, false-positive guidance,
fixture id, and scan-mode requirements (CLX-4.3 / #4861). See
[scanner evaluation](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/scanner_evaluation.md).

Fetch this catalog programmatically with `GET /v1/lint/rules` (see
[Lint and check quality](./lint-and-quality.md)).


## Pack: `a2a`

### `a2a.apikey-in-query` {#a2a-apikey-in-query}

- **Category:** security
- **Default severity:** warning
- **Rationale:** Flag API keys sent in the query string.
- **Security weight:** 1.0

### `a2a.duplicate-skill-id` {#a2a-duplicate-skill-id}

- **Category:** naming
- **Default severity:** error
- **Rationale:** Flag skill ids repeated within one card.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#a2a-duplicate-skill-id
- **Remediation:** Give each skill in `skills` a unique `id` (rename the repeat, or merge the two skills if they are the same).
- **False-positive guidance:** None expected: the A2A specification requires skill ids to be unique within a card.
- **Fixture:** `catalog/a2a-duplicate-skill-id`
- **Scan modes:** `lint`

### `a2a.insecure-endpoint` {#a2a-insecure-endpoint}

- **Category:** security
- **Default severity:** warning
- **Rationale:** Flag endpoints served over plain HTTP.
- **Security weight:** 1.0

### `a2a.missing-required-field` {#a2a-missing-required-field}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Flag cards missing a field the A2A spec requires.

### `a2a.no-security` {#a2a-no-security}

- **Category:** security
- **Default severity:** warning
- **Rationale:** Flag cards that declare no security at all.
- **Security weight:** 1.0

### `a2a.security-undeclared-scheme` {#a2a-security-undeclared-scheme}

- **Category:** security
- **Default severity:** error
- **Rationale:** Flag security requirements that name an undefined scheme.
- **Security weight:** 1.0
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#a2a-security-undeclared-scheme
- **Remediation:** Define the scheme under `securitySchemes`, or correct the name in the card's or the skill's `security` list.
- **False-positive guidance:** A card served to anonymous callers may omit schemes that only its authenticated extended card declares; import the extended card instead.
- **Fixture:** `catalog/a2a-security-undeclared-scheme`
- **Scan modes:** `lint`

### `a2a.skill-missing-description` {#a2a-skill-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** Flag skills with no description.

### `a2a.skill-missing-tags` {#a2a-skill-missing-tags}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag skills with no tags.

### `a2a.skill-without-modes` {#a2a-skill-without-modes}

- **Category:** structure
- **Default severity:** info
- **Rationale:** Flag skills with no input or output modes and no card default.

### `a2a.unknown-scheme-type` {#a2a-unknown-scheme-type}

- **Category:** security
- **Default severity:** warning
- **Rationale:** Flag security schemes whose type A2A does not define.
- **Security weight:** 1.0


## Pack: `acp`

### `acp.agent-missing-description` {#acp-agent-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** Flag agents with no description.

### `acp.capability-missing-description` {#acp-capability-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** Flag capabilities with no description.

### `acp.duplicate-agent-name` {#acp-duplicate-agent-name}

- **Category:** naming
- **Default severity:** error
- **Rationale:** Flag agent names repeated within one listing.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#acp-duplicate-agent-name
- **Remediation:** Rename one of the agents so every name in the `GET /agents` listing is unique.
- **False-positive guidance:** A listing concatenated from two servers can repeat a name legitimately; import each server's listing separately.
- **Fixture:** `catalog/acp-duplicate-agent-name`
- **Scan modes:** `lint`

### `acp.duplicate-capability-name` {#acp-duplicate-capability-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Flag capability names repeated within one agent.

### `acp.invalid-agent-name` {#acp-invalid-agent-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Flag agent names that are not RFC 1123 labels.

### `acp.missing-license` {#acp-missing-license}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag agents that declare no SPDX license.

### `acp.missing-tags` {#acp-missing-tags}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag agents with no tags and no domains.

### `acp.no-capabilities` {#acp-no-capabilities}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag agents that declare no capabilities.

### `acp.untyped-content` {#acp-untyped-content}

- **Category:** structure
- **Default severity:** info
- **Rationale:** Flag agents whose input or output content types are undeclared or */*.


## Pack: `agents-manifest`

### `agents-manifest.broken-endpoint-ref` {#agents-manifest-broken-endpoint-ref}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Flag endpoint and action addresses that do not resolve to a URL.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#agents-manifest-broken-endpoint-ref
- **Remediation:** Write the endpoint as an absolute https URL, or give the manifest its site (`site.url` in agents.json, `domain` in agent.json) so relative paths resolve.
- **False-positive guidance:** An agents.txt or llms.txt imported from a file has no site, so a relative path cannot resolve; import it from its URL (or with discovery) instead.
- **Fixture:** `catalog/agents-manifest-broken-endpoint-ref`
- **Scan modes:** `lint`

### `agents-manifest.duplicate-action-id` {#agents-manifest-duplicate-action-id}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Flag AWP action ids used by more than one action.

### `agents-manifest.duplicate-endpoint` {#agents-manifest-duplicate-endpoint}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Flag a protocol endpoint declared more than once.

### `agents-manifest.insecure-endpoint` {#agents-manifest-insecure-endpoint}

- **Category:** security
- **Default severity:** warning
- **Rationale:** Flag agent endpoints served over plain http.
- **Security weight:** 1.0

### `agents-manifest.no-agent-endpoints` {#agents-manifest-no-agent-endpoints}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag manifests that declare no A2A, ACP or MCP endpoint.

### `agents-manifest.undeclared-via` {#agents-manifest-undeclared-via}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Flag AWP actions routed via a protocol the manifest does not declare.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#agents-manifest-undeclared-via
- **Remediation:** Declare the protocol under `protocols` with its `endpoint`, or correct the action's `via`.
- **False-positive guidance:** None expected: the Agent Web Protocol requires every `via` to name a declared protocol.
- **Fixture:** `catalog/agents-manifest-undeclared-via`
- **Scan modes:** `lint`


## Pack: `arazzo`

### `arazzo.async-source-before-1-1` {#arazzo-async-source-before-1-1}

- **Category:** version
- **Default severity:** error
- **Rationale:** An AsyncAPI sourceDescription requires Arazzo 1.1 or newer.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#arazzo-async-source-before-1-1
- **Remediation:** Declare `arazzo: 1.1.0` at the top of the document, or change the source description's `type` to one Arazzo 1.0 defines (`openapi` or `arazzo`).
- **False-positive guidance:** Only false if a runner is known to accept the 1.1 source types under a 1.0 marker; the published 1.0 schema does not, so prefer declaring 1.1.
- **Fixture:** `catalog/arazzo-async-source-before-1-1`
- **Scan modes:** `lint`

### `arazzo.dangling-operation-id` {#arazzo-dangling-operation-id}

- **Category:** reference
- **Default severity:** error
- **Rationale:** Step operationId must resolve to an embedded sourceDescription.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#arazzo-dangling-operation-id
- **Remediation:** Point the step's operationId at an operation declared in an embedded OpenAPI sourceDescription, or remove the step.
- **False-positive guidance:** Only false if the engine cannot see an operation that exists only in an external (non-embedded) source — embed the description or switch to operationRef.
- **Fixture:** `catalog/arazzo-dangling-operation-id`
- **Scan modes:** `lint`

### `arazzo.missing-success-criteria` {#arazzo-missing-success-criteria}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Every workflow step should declare successCriteria.

### `arazzo.unused-workflow-input` {#arazzo-unused-workflow-input}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Workflow inputs should be referenced by at least one step.

### `arzzo.unresolvable-operation-ref` {#arzzo-unresolvable-operation-ref}

- **Category:** reference
- **Default severity:** error
- **Rationale:** Step operationRef must point at a declared sourceDescription.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#arzzo-unresolvable-operation-ref
- **Remediation:** Use a local JSON Pointer under #/sourceDescriptions/<name>/… for a declared source, or fix the sourceDescription name.
- **False-positive guidance:** External HTTP operationRef targets are out of scope for static resolution — prefer embedded sources for gateable workflows.
- **Fixture:** `catalog/arzzo-unresolvable-operation-ref`
- **Scan modes:** `lint`


## Pack: `asyncapi`

### `asyncapi.message-missing-name` {#asyncapi-message-missing-name}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every event message should carry an author-given name.

### `asyncapi.message-missing-payload` {#asyncapi-message-missing-payload}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Every event message should declare a payload schema.

### `asyncapi.message-unstable-name` {#asyncapi-message-unstable-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Message names should be author-chosen, not generator output.

### `asyncapi.server-missing-protocol` {#asyncapi-server-missing-protocol}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Every server should declare its transport protocol.

### `asyncapi.server-missing-security` {#asyncapi-server-missing-security}

- **Category:** structure
- **Default severity:** info
- **Rationale:** Servers should usually declare a security scheme.


## Pack: `avro`

### `avro.alias-conflict` {#avro-alias-conflict}

- **Category:** naming
- **Default severity:** error
- **Rationale:** An Avro alias must not collide with another field's or named type's name or alias.
- **Reference:** https://avro.apache.org/docs/1.12.0/specification/
- **Remediation:** Remove or rename the alias so it names only the element it belongs to.
- **False-positive guidance:** Not a false positive: an alias shared by two fields of a record, or two named types, matches both during resolution.
- **Fixture:** `catalog/avro-alias-conflict`
- **Scan modes:** `lint`

### `avro.doc-ignored` {#avro-doc-ignored}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** An Avro doc should be a string on a field or named type, where tools keep it.

### `avro.invalid-alias` {#avro-invalid-alias}

- **Category:** naming
- **Default severity:** error
- **Rationale:** An Avro alias must be a valid Avro name.
- **Reference:** https://avro.apache.org/docs/1.12.0/specification/
- **Remediation:** Spell the alias as an Avro name ([A-Za-z_][A-Za-z0-9_]*; dotted parts for a named type's full name).
- **False-positive guidance:** Not a false positive: the Avro specification requires aliases to be valid names.
- **Fixture:** `catalog/avro-invalid-alias`
- **Scan modes:** `lint`

### `avro.invalid-default` {#avro-invalid-default}

- **Category:** structure
- **Default severity:** error
- **Rationale:** An Avro default must be a value of its type (a union's, of its first branch).
- **Reference:** https://avro.apache.org/docs/1.12.0/specification/
- **Remediation:** Change the default to a value of the field's type; for a union, put the branch the default belongs to first (for null, write ["null", T]).
- **False-positive guidance:** Not a false positive: the Avro specification requires a default to match the field's schema, and a union's default its first branch.
- **Fixture:** `catalog/avro-invalid-default`
- **Scan modes:** `lint`

### `avro.invalid-union` {#avro-invalid-union}

- **Category:** structure
- **Default severity:** error
- **Rationale:** An Avro union must not nest a union or repeat a branch.
- **Reference:** https://avro.apache.org/docs/1.12.0/specification/
- **Remediation:** Flatten nested unions into one, and list each unnamed type and each named type only once.
- **False-positive guidance:** Not a false positive: the Avro specification forbids unions that directly contain unions or repeat a type.
- **Fixture:** `catalog/avro-invalid-union`
- **Scan modes:** `lint`

### `avro.optional-union-missing-default` {#avro-optional-union-missing-default}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An optional ["null", T] Avro field should declare "default": null.

### `avro.optional-union-null-first` {#avro-optional-union-null-first}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An optional Avro field should be ["null", T] so it can default to null.

### `avro.redundant-alias` {#avro-redundant-alias}

- **Category:** naming
- **Default severity:** info
- **Rationale:** An Avro alias should differ from the name it aliases.


## Pack: `common`

### `common.api-missing-description` {#common-api-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** The API artifact should carry a top-level description.

### `common.channel-missing-description` {#common-channel-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every event channel should describe itself.

### `common.field-missing-description` {#common-field-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every field should describe itself.

### `common.message-missing-description` {#common-message-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every message payload should describe itself.

### `common.operation-missing-description` {#common-operation-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** Every operation should describe what it does.

### `common.type-missing-description` {#common-type-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** Every named type should describe itself.

### `common.unstable-field-name` {#common-unstable-field-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Field names should be author-chosen, not generator output.

### `common.unstable-type-name` {#common-unstable-type-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Type names should be author-chosen, not generator output.


## Pack: `data-contract`

### `data-contract.classification-missing` {#data-contract-classification-missing}

- **Category:** governance
- **Default severity:** info
- **Rationale:** Personal data that is not labelled cannot be governed, masked or audited.
- **Remediation:** Classify the columns that carry personal or restricted data — an ODCS `classification` / `criticalDataElement`, or a dbt `meta` marker.
- **Fixture:** `catalog/data-contract-classification-missing`

### `data-contract.column-description-coverage` {#data-contract-column-description-coverage}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** A column nobody described is a column consumers guess at.
- **Remediation:** Describe the table's columns: at least three quarters of them need a `description` before the table reads as documented.
- **Fixture:** `catalog/data-contract-column-description-coverage`

### `data-contract.freshness-missing` {#data-contract-freshness-missing}

- **Category:** governance
- **Default severity:** info
- **Rationale:** Freshness is the service level consumers of a dataset ask about first.
- **Remediation:** State a freshness expectation — an ODCS `frequency`/`latency` SLA property, or a dbt source `freshness` block with `warn_after`/`error_after`.
- **Fixture:** `catalog/data-contract-freshness-missing`

### `data-contract.owner-missing` {#data-contract-owner-missing}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** A dataset nobody owns is a dataset nobody fixes.
- **Remediation:** Declare an owner: an ODCS `team[]` member, a dbt `meta.owner`, or an exposure `owner` block naming the team accountable for the dataset.
- **Fixture:** `catalog/data-contract-owner-missing`

### `data-contract.owner-unresolvable` {#data-contract-owner-unresolvable}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** An ownership entry with no name, address or channel cannot actually be reached.
- **Remediation:** Give the ownership entry a `name`, `username`, `email` or `channel` — a role with no contact is a label, not an owner.
- **Fixture:** `catalog/data-contract-owner-unresolvable`

### `data-contract.primary-key-missing` {#data-contract-primary-key-missing}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Without a declared key, a row cannot be addressed, deduplicated or joined reliably.
- **Remediation:** Declare row identity: an ODCS `primaryKey`/`unique` property, a dbt `unique` test, or a model-contract `primary_key` constraint.
- **Fixture:** `catalog/data-contract-primary-key-missing`

### `data-contract.quality-rules-missing` {#data-contract-quality-rules-missing}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** A critical column with no declared check is an expectation held only in somebody's head.
- **Remediation:** Attach a quality rule to the column — an ODCS `quality[]` entry, or a dbt data test — or attach a table-level rule that covers it.
- **Fixture:** `catalog/data-contract-quality-rules-missing`

### `data-contract.retention-undocumented` {#data-contract-retention-undocumented}

- **Category:** governance
- **Default severity:** info
- **Rationale:** Undocumented retention is a compliance question nobody can answer from the contract.
- **Remediation:** State how long the data is kept: an ODCS `retention` SLA property, or a custom property naming the retention window.
- **Fixture:** `catalog/data-contract-retention-undocumented`

### `data-contract.server-missing` {#data-contract-server-missing}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** A contract that never says where the data is served describes a table nobody can find.
- **Remediation:** Declare the serving location — an ODCS `servers[]` entry, or the database/schema/alias a dbt resource materializes to.
- **Fixture:** `catalog/data-contract-server-missing`

### `data-contract.sla-missing` {#data-contract-sla-missing}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** Without a stated service level, a consumer cannot tell a nightly batch from a streaming table.
- **Remediation:** Declare `slaProperties[]` (ODCS) or a source `freshness` block (dbt) stating the latency, frequency or availability the dataset promises.
- **Fixture:** `catalog/data-contract-sla-missing`

### `data-contract.status-missing` {#data-contract-status-missing}

- **Category:** governance
- **Default severity:** info
- **Rationale:** A consumer cannot tell a draft dataset from a production one without a status.
- **Remediation:** Declare a lifecycle `status` (`draft`, `active`, `deprecated`, `retired`).
- **Fixture:** `catalog/data-contract-status-missing`

### `data-contract.version-missing` {#data-contract-version-missing}

- **Category:** governance
- **Default severity:** warning
- **Rationale:** An unversioned contract cannot be changed safely: nothing distinguishes revisions.
- **Remediation:** Declare the contract's own `version` (ODCS `version`, a dbt project `version`), so consumers can pin one.
- **Fixture:** `catalog/data-contract-version-missing`


## Pack: `examples`

### `examples.non-conforming-example` {#examples-non-conforming-example}

- **Category:** validation
- **Default severity:** warning
- **Rationale:** An example that does not satisfy its own schema ships a payload consumers cannot use — docs render it, mocks replay it, and generated clients seed fixtures from it.


## Pack: `graphql`

### `graphql.argument-missing-description` {#graphql-argument-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every operation argument should describe itself.

### `graphql.composition-error` {#graphql-composition-error}

- **Category:** composition
- **Default severity:** error
- **Rationale:** A composition error reported by `rover supergraph compose` over the imported subgraph set.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#graphql-composition-error
- **Remediation:** Fix the subgraph the finding names so the set composes (run `rover supergraph compose` locally for the full report), then re-import.
- **False-positive guidance:** The verdict is captured at import time; if the subgraphs changed since, re-import the set to refresh it.
- **Fixture:** `catalog/graphql-composition-error`
- **Scan modes:** `lint`

### `graphql.composition-invalid-key` {#graphql-composition-invalid-key}

- **Category:** composition
- **Default severity:** error
- **Rationale:** A @key(fields:) selection must name fields its type declares in that subgraph.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#graphql-composition-invalid-key
- **Remediation:** Make the @key selection reference fields the type declares in the named subgraph (declare the field, or fix the selection).
- **False-positive guidance:** Nested key selections are checked at the top level only; a top-level field reported missing is genuinely undeclared in that subgraph's file.
- **Fixture:** `catalog/graphql-composition-invalid-key`
- **Scan modes:** `lint`

### `graphql.composition-non-shareable-field` {#graphql-composition-non-shareable-field}

- **Category:** composition
- **Default severity:** error
- **Rationale:** A field resolved by more than one subgraph must be @shareable in every subgraph that resolves it.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#graphql-composition-non-shareable-field
- **Remediation:** Mark the field @shareable in every subgraph that resolves it, mark the stub copies @external, or move the field to a single owning subgraph.
- **False-positive guidance:** Key fields and @external stubs are already exempt; a hit means two subgraphs genuinely both resolve the field.
- **Fixture:** `catalog/graphql-composition-non-shareable-field`
- **Scan modes:** `lint`

### `graphql.composition-unresolvable-selection` {#graphql-composition-unresolvable-selection}

- **Category:** composition
- **Default severity:** error
- **Rationale:** A @requires/@provides selection must reference fields some subgraph declares.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#graphql-composition-unresolvable-selection
- **Remediation:** Point the @requires/@provides selection at fields declared on the target type in some subgraph (declare the field there, or fix the selection).
- **False-positive guidance:** The check unions declarations across the whole set; a hit means no subgraph declares the selected field at all.
- **Fixture:** `catalog/graphql-composition-unresolvable-selection`
- **Scan modes:** `lint`

### `graphql.enum-value-missing-description` {#graphql-enum-value-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every enum value should describe itself.

### `graphql.naming-argument-camel-case` {#graphql-naming-argument-camel-case}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Operation arguments should be camelCase.

### `graphql.naming-enum-value-upper-case` {#graphql-naming-enum-value-upper-case}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Enum values should be UPPER_CASE.

### `graphql.naming-field-camel-case` {#graphql-naming-field-camel-case}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Fields and operations should be camelCase.

### `graphql.naming-type-pascal-case` {#graphql-naming-type-pascal-case}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Type definitions should be PascalCase.

### `graphql.require-deprecation-reason` {#graphql-require-deprecation-reason}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** A @deprecated entity should carry a deprecation reason.


## Pack: `intake`

### `intake.blocked-external-ref` {#intake-blocked-external-ref}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An external $ref pointing at a non-public address (loopback, RFC1918, link-local, or the cloud metadata endpoint) or at a non-HTTP scheme is refused by the SSRF guard and is never fetched. Publish the referenced document at a public HTTPS URL, or bundle it into the import instead of referencing it.

### `intake.overlay-action-invalid` {#intake-overlay-action-invalid}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An OpenAPI Overlay action that declares no target, neither `update` nor `remove: true`, an invalid JSONPath, or an `update` value whose type does not fit the selected node cannot be applied as written (Overlay 1.0). Fix the action so the modification it describes actually reaches the resolved document.

### `intake.overlay-unmatched-target` {#intake-overlay-unmatched-target}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An OpenAPI Overlay action whose `target` JSONPath matches nothing in the base document has no effect: the modification the overlay describes was silently skipped everywhere the resolved document is used. Fix the target expression, or remove the action if the construct it targeted no longer exists in the base.

### `intake.unresolved-external-ref` {#intake-unresolved-external-ref}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An external $ref that is never resolved leaves the imported model incomplete: the referenced messages, schemas, or types are missing from every downstream view (diff, lint, export) with no indication that anything was dropped. Enable remote $ref resolution for the import, bundle the referenced documents into the upload, or inline the definitions in the source document.


## Pack: `k8s-crd`

### `k8s-crd.required-field-hygiene` {#k8s-crd-required-field-hygiene}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Flag required lists with missing, duplicate, or undescribed fields.

### `k8s-crd.structural-schema-pruning` {#k8s-crd-structural-schema-pruning}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Flag non-structural JSON Schema keywords and preserve-unknown-fields hygiene issues that affect Kubernetes pruning.


## Pack: `llm-tools`

### `llm-tools.duplicate-tool-name` {#llm-tools-duplicate-tool-name}

- **Category:** naming
- **Default severity:** error
- **Rationale:** Flag colliding tool names within a bundle.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#llm-tools-duplicate-tool-name
- **Remediation:** Give each tool a unique `name` within the bundle (rename or drop duplicates).
- **False-positive guidance:** Cross-dialect wrappers that intentionally alias the same tool should still expose a single canonical name to agents.
- **Fixture:** `catalog/llm-tools-duplicate-tool-name`
- **Scan modes:** `lint`

### `llm-tools.param-missing-description` {#llm-tools-param-missing-description}

- **Category:** quality
- **Default severity:** warning
- **Rationale:** Flag parameters without descriptions.

### `llm-tools.prefer-enum-over-freetext` {#llm-tools-prefer-enum-over-freetext}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag free-text parameters that look enumerable.

### `llm-tools.required-field-hygiene` {#llm-tools-required-field-hygiene}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Flag required lists with missing or duplicate names.

### `llm-tools.tool-missing-description` {#llm-tools-tool-missing-description}

- **Category:** quality
- **Default severity:** warning
- **Rationale:** Flag tools with no description.

### `llm-tools.tool-weak-description` {#llm-tools-tool-weak-description}

- **Category:** quality
- **Default severity:** info
- **Rationale:** Flag tools whose description is too short or equals the name.


## Pack: `odata`

### `odata.csdl-schema` {#odata-csdl-schema}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** OData CSDL should validate against the OASIS CSDL JSON schema.

### `odata.csdl-xsd` {#odata-csdl-xsd}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** OData v4 CSDL XML should validate against the OASIS EDMX / EDM XML schemas.

### `odata.entity-key` {#odata-entity-key}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Every OData entity type must declare or inherit a key of non-nullable primitive properties.
- **Reference:** https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/odata-csdl-xml-v4.01.html
- **Remediation:** Declare a Key whose PropertyRefs name existing primitive properties marked Nullable="false"; on a derived type, remove the Key and inherit the base type's.
- **False-positive guidance:** Not a false positive: OData CSDL requires every non-abstract entity type to declare or inherit a key, and key properties to be non-nullable primitives.
- **Fixture:** `catalog/odata-entity-key`
- **Scan modes:** `lint`

### `odata.unresolved-reference` {#odata-unresolved-reference}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Every type, entity set, partner, binding and operation an OData document names must be declared.
- **Reference:** https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/odata-csdl-xml-v4.01.html
- **Remediation:** Declare the missing element, fix the spelling, or qualify the name with the namespace (or alias) that declares it; for a type in another document, add an edmx:Reference that includes its namespace.
- **False-positive guidance:** Names in namespaces the document only references are never reported. A finding names something declared nowhere in the document or its merged set.
- **Fixture:** `catalog/odata-unresolved-reference`
- **Scan modes:** `lint`


## Pack: `openapi`

### `compatibility.breaking` {#compatibility-breaking}

- **Category:** compatibility
- **Default severity:** error
- **Rationale:** A change relative to the base revision breaks existing consumers.
- **Reference:** https://apiome.github.io/apiome/build/lint-rules#compatibility-breaking
- **Remediation:** Restore the removed/changed contract surface, introduce a new path or version, or deliberately gate with a documented breaking-change process.
- **False-positive guidance:** Diff noise from reorder-only or documentation-only revisions should not appear; if it does, file a scanner bug with the base/head pair.
- **Fixture:** `catalog/compatibility-breaking`
- **Scan modes:** `breaking`, `lint`

### `compatibility.unknown` {#compatibility-unknown}

- **Category:** compatibility
- **Default severity:** warning
- **Rationale:** A change relative to the base revision has an unclassified compatibility impact.

### `documentation.info-missing-description` {#documentation-info-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** The API info block should describe what the API is for.

### `documentation.operation-missing-summary` {#documentation-operation-missing-summary}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** An operation needs a summary or description to produce usable reference docs.

### `documentation.property-missing-description` {#documentation-property-missing-description}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Every property should describe what it holds.

### `documentation.property-missing-example` {#documentation-property-missing-example}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Scalar leaf properties should carry an example so docs and mocks stay realistic.

### `documentation.schema-missing-description` {#documentation-schema-missing-description}

- **Category:** documentation
- **Default severity:** warning
- **Rationale:** A schema without a description forces consumers to guess what it models.

### `naming.property-name` {#naming-property-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Property names should be camelCase or snake_case for predictable client bindings.

### `naming.schema-pascal-case` {#naming-schema-pascal-case}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Component schema names should be PascalCase so generated client types are idiomatic.

### `structure.unbounded-array` {#structure-unbounded-array}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** An array without maxItems permits unbounded payloads that strain clients and servers.


## Pack: `openrpc`

### `openrpc.method-described` {#openrpc-method-described}

- **Category:** documentation
- **Default severity:** info
- **Rationale:** Methods should have a summary or a description.

### `openrpc.required-params-first` {#openrpc-required-params-first}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Required parameters must come before optional ones.
- **Reference:** https://spec.open-rpc.org/#method-object
- **Remediation:** Move every required parameter ahead of the first optional parameter.
- **False-positive guidance:** Not a false positive: the OpenRPC specification requires every required parameter to be positioned before any optional parameter.
- **Fixture:** `catalog/openrpc-required-params-first`
- **Scan modes:** `lint`

### `openrpc.reserved-method-name` {#openrpc-reserved-method-name}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** Method names must not begin with the reserved 'rpc.' prefix.

### `openrpc.unique-method-names` {#openrpc-unique-method-names}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Method names must be unique.
- **Reference:** https://spec.open-rpc.org/#openrpc-object
- **Remediation:** Rename one of the methods, or merge them into one method.
- **False-positive guidance:** Not a false positive: the OpenRPC specification requires unique method names, so callers cannot reach both methods.
- **Fixture:** `catalog/openrpc-unique-method-names`
- **Scan modes:** `lint`

### `openrpc.unique-param-names` {#openrpc-unique-param-names}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Parameter names must be unique within a method.
- **Reference:** https://spec.open-rpc.org/#method-object
- **Remediation:** Give each parameter of the method its own name.
- **False-positive guidance:** Not a false positive: the OpenRPC specification forbids duplicated parameters within a method.
- **Fixture:** `catalog/openrpc-unique-param-names`
- **Scan modes:** `lint`


## Pack: `protobuf`

### `protobuf.editions.closed-enum` {#protobuf-editions-closed-enum}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** A closed enum cannot receive a value a newer peer added.

### `protobuf.editions.delimited-encoding` {#protobuf-editions-delimited-encoding}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Editions 'message_encoding = DELIMITED' is the proto2 group wire format.

### `protobuf.editions.legacy-json-format` {#protobuf-editions-legacy-json-format}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Editions 'json_format = LEGACY_BEST_EFFORT' gives up the JSON guarantee.

### `protobuf.editions.utf8-validation-off` {#protobuf-editions-utf8-validation-off}

- **Category:** structure
- **Default severity:** info
- **Rationale:** Editions 'utf8_validation = NONE' admits strings with no JSON encoding.

### `protobuf.field-no-required` {#protobuf-field-no-required}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Fields should not be 'required'.

### `protobuf.package-version-suffix` {#protobuf-package-version-suffix}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** A package should carry a version suffix (foo.v1).

### `protobuf.reserved-on-deletion` {#protobuf-reserved-on-deletion}

- **Category:** structure
- **Default severity:** info
- **Rationale:** Removed field/value numbers should be reserved, not left as gaps.


## Pack: `provenance`

### `provenance.inferred-construct-ratio` {#provenance-inferred-construct-ratio}

- **Category:** provenance
- **Default severity:** info
- **Rationale:** Reports the share of constructs Apiome inferred rather than read from a declaration; raise it to error in a style guide to keep inferred APIs from being published.


## Pack: `thrift`

### `thrift.enum-explicit-values` {#thrift-enum-explicit-values}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Enum values should have explicit numbers.

### `thrift.field-no-required` {#thrift-field-no-required}

- **Category:** structure
- **Default severity:** warning
- **Rationale:** Fields should not be 'required'.

### `thrift.namespace-declared` {#thrift-namespace-declared}

- **Category:** naming
- **Default severity:** info
- **Rationale:** A Thrift document should declare a namespace.

### `thrift.oneway-void` {#thrift-oneway-void}

- **Category:** structure
- **Default severity:** error
- **Rationale:** A oneway method must return void and declare no throws.
- **Reference:** https://thrift.apache.org/docs/idl#service
- **Remediation:** Make the method return `void` and drop its `throws`, or remove `oneway` so the caller waits for the reply.
- **False-positive guidance:** Not a false positive: the Thrift compiler rejects a oneway method with a return value or exceptions.
- **Fixture:** `catalog/thrift-oneway-void`
- **Scan modes:** `lint`

### `thrift.unique-field-ids` {#thrift-unique-field-ids}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Field, parameter and exception ids must be unique.
- **Reference:** https://thrift.apache.org/docs/idl#field
- **Remediation:** Give each field, parameter or exception of the struct or method its own id; never reuse the id of a removed field.
- **False-positive guidance:** Not a false positive: the Thrift compiler rejects duplicate ids, so the document cannot be compiled as written.
- **Fixture:** `catalog/thrift-unique-field-ids`
- **Scan modes:** `lint`


## Pack: `wsi`

### `wsi.binding-style` {#wsi-binding-style}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: a binding must be all rpc-literal or all document-literal.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Make every operation of the binding the same style, or split the operations into two bindings.
- **False-positive guidance:** Not a false positive: R2705 requires each binding to be wholly rpc-literal or wholly document-literal.
- **Fixture:** `catalog/wsdl-binding-style`
- **Scan modes:** `lint`

### `wsi.document-literal` {#wsi-document-literal}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: a document-literal body references at most one part, defined by element, with no namespace.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Reference one part defined with element= (wrap several values in one element), and remove namespace= from soap:body.
- **False-positive guidance:** Not a false positive: these are Basic Profile requirements on document-literal bindings.
- **Fixture:** `catalog/wsdl-document-literal`
- **Scan modes:** `lint`

### `wsi.literal-use` {#wsi-literal-use}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: SOAP bindings must use literal, not encoded, messages.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Describe the message with XML Schema elements and set use="literal" on every soap:body, soap:header, soap:headerfault and soap:fault.
- **False-positive guidance:** Not a false positive: R2706 forbids encoded use in a conformant description; only legacy RPC/encoded toolkits accept it.
- **Fixture:** `catalog/wsdl-literal-use`
- **Scan modes:** `lint`

### `wsi.rpc-literal` {#wsi-rpc-literal}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: an rpc-literal body references parts defined by type and names a namespace.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Define rpc-literal parts with type=, and give soap:body a namespace= naming the wrapper's namespace.
- **False-positive guidance:** Not a false positive: these are Basic Profile requirements on rpc-literal bindings.
- **Fixture:** `catalog/wsdl-rpc-literal`
- **Scan modes:** `lint`

### `wsi.unique-operation-signature` {#wsi-unique-operation-signature}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: the operations of a binding must differ on the wire.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Give each operation its own request element (or rpc operation name), or distinct soapAction values.
- **False-positive guidance:** Reported only when both the body element and the soapAction are identical, which no receiver can disambiguate.
- **Fixture:** `catalog/wsdl-unique-operation-signature`
- **Scan modes:** `lint`

### `wsi.unique-soap-action` {#wsi-unique-soap-action}

- **Category:** naming
- **Default severity:** warning
- **Rationale:** The operations of a binding should have distinct soapAction values.

### `wsi.unresolved-import` {#wsi-unresolved-import}

- **Category:** structure
- **Default severity:** error
- **Rationale:** Every wsdl:import, xs:import and xs:include must resolve within the import.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Upload the imported documents with the description (a .zip or file set), import the live service URL so they are fetched, or inline them (?singleWsdl).
- **False-positive guidance:** A single file uploaded without its imports reports every external import; re-import it with its members before treating the finding as a defect of the service.
- **Fixture:** `catalog/wsdl-unresolved-import`
- **Scan modes:** `lint`

### `wsi.wsdl-import-target` {#wsi-wsdl-import-target}

- **Category:** structure
- **Default severity:** error
- **Rationale:** WS-I: wsdl:import must have a location and import only WSDL descriptions.
- **Reference:** https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html
- **Remediation:** Give the wsdl:import a location, and import XML Schema documents with xs:import in wsdl:types instead.
- **False-positive guidance:** Not a false positive: the Basic Profile requires these import forms.
- **Fixture:** `catalog/wsdl-wsdl-import-target`
- **Scan modes:** `lint`
