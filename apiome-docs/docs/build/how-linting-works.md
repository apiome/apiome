---
title: "How linting works"
description: "Rule packs, the score and grade, and where every format's findings appear."
sidebar_position: 4.5
tags: [lint, quality]
---

Every API Apiome holds is linted the same way, whatever format it came in: OpenAPI, AsyncAPI,
GraphQL, Protobuf, Avro, RAML, Smithy, a data contract or an agent card. Apiome reads each one
into a common model, runs **rule packs** over it, and rolls the findings up into a **score out of
100**, an **A–F grade** and a **fingerprint**. Because one engine does this for every format,
a GraphQL schema and an OpenAPI document are graded on the same scale and shown in the same places.

Use this page to understand where a finding comes from and why a score is what it is. To read or
gate on a score, see [Lint and check quality](./lint-and-quality.md); for every rule, see
[Built-in lint rules](./lint-rules.md).

## Rule packs

A **rule pack** is an ordered set of rules. Each rule has a stable id (`common.type-missing-description`),
a category (documentation, naming, structure, security, …) and a default severity (`error`,
`warning` or `info`). Every finding names the rule that raised it, so it always links back to
[Built-in lint rules](./lint-rules.md). The same input always gives the same findings in the same order.

Which packs run depends on the item:

| Pack | Runs for |
| --- | --- |
| `common` | Every item. Missing descriptions (on the API, types, fields, operations, messages and channels) and unstable, auto-generated names that will not survive a re-import |
| `examples` | Every item that kept its source document. Each example must satisfy the schema beside it |
| `provenance` | Every item where Apiome inferred part of the API rather than reading it from a declaration |
| A **format pack** | Items in that format: `openapi`, `asyncapi`, `graphql`, `protobuf`, `avro`, `raml`, `smithy`, `typespec`, `thrift`, `odata`, `openrpc`, `apiblueprint`, `arazzo`, `fhir`, `k8s-crd`, `wsi` (WSDL), `a2a`, `acp`, `agents-manifest`, `llm-tools` and others |
| A **family pack** | Every item of a family, whatever its format. `data-contract` runs for ODCS contracts and dbt projects alike |

A style guide can change a rule's severity or turn a pack off; see
[Style guides govern every lint run](./lint-and-quality.md#style-guides-govern-every-lint-run).

## Linters a format's community uses

Some formats have a linter their community trusts. Where Apiome bundles it, it runs beside the
native packs:

- **AsyncAPI** — Spectral's `spectral:asyncapi` ruleset runs on every AsyncAPI import. Its findings
  appear as `asyncapi.spectral.*` rules and count toward the score.
- **API Blueprint** — drafter's errors and warnings appear as `apiblueprint.drafter-*` rules.
- **Protobuf** and **GraphQL** — `buf lint` and `graphql-eslint` run after the import and are
  recorded as lint evidence for the revision
  (`GET …/lint/evidence` in the [lint REST reference](/reference/rest/lint)). They do not change the score.

If one of these tools is missing, times out or crashes, the import does not fail: the native
packs still lint the item. For `buf lint` and `graphql-eslint`, the failure is recorded as evidence,
so you can see the tool did not run.

## The score, the grade and the fingerprint

The score starts at 100. Each finding takes off a penalty by severity: **10** for an `error`,
**4** for a `warning`, **1** for `info`. One rule can take off at most **20**, so a single noisy
rule cannot sink the score. The score never goes below 0.

| Grade | Score |
| --- | --- |
| **A** | 90–100 |
| **B** | 80–89 |
| **C** | 70–79 |
| **D** | 60–69 |
| **F** | below 60 |

The **fingerprint** is a hash of the score, the grade and the findings. Two reports with the same
fingerprint say exactly the same thing. The security score shown beside the grade is a separate
number with its own weights; see [Axis score](./axis-score.md).

## The stored score and the live report

When an import or conversion commits a new version, its score is **captured** and stored on the
version, with its fingerprint. Lists and badges read that stored score, so showing them never
re-lints anything.

Opening a report computes it from the version as it is now. When the fingerprints differ, the
stored score is out of date, and each surface says so:

| Where | What you see |
| --- | --- |
| A version's lint report (**Versions** → the grade chip) | *The stored quality score (B · 84) is out of date — this report was recomputed from the current revision.* |
| A catalog item's **Lint & score** tab | The score captured at import (labelled **Stored report**; **Computed live** when none was captured). When the live score differs, a note under it reads *Converted OpenAPI lint: B · 84/100* |
| `apiome lint` | A `Stored score: 84/100  (grade B) — out of date; showing live recompute above.` line |
| `GET …/lint` | `capturedScore`, `capturedGrade`, `capturedReportFingerprint` and `scoreIsStale` |

A comparison against a base version (`--base-version`, `baseRevisionId`) is never flagged stale:
it adds breaking-change findings, so it is never expected to match the stored score.

<Screenshot id="catalog-item-lint" alt="The Lint & score tab: requirement counts, the lint score and findings" />

## Where findings appear

| Surface | Where |
| --- | --- |
| **Designer** | The grade and findings for the version you are editing |
| **Versions** | A grade chip on every revision; click it for the full report |
| **Catalog** | The **Lint** score in an item's header, and its **Lint & score** tab ([Catalog](../bring-in/catalog.mdx)) |
| **Lint posture** | Every finding across the workspace, to triage, assign and waive ([Lint posture](../govern/lint-posture.mdx)) |
| CLI | `apiome lint --project <id> --version <label>`, with `--min-grade` to gate CI ([`apiome lint`](/reference/cli/lint)) |
| REST | `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint` and `GET /v1/lint/rules` ([lint REST reference](/reference/rest/lint)) |

Every surface reads the same report, scoped to your workspace, so they always agree.

## Related

- [Lint and check quality](./lint-and-quality.md) — read a report, gate on a grade, when linting runs
- [Built-in lint rules](./lint-rules.md) — every rule, by pack
- [Custom lint rules](./custom-rules.md) — write your own rules
- [Axis score](./axis-score.md) — the security score and the other axes
