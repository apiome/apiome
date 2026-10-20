---
title: "Axis score algorithm"
description: "How the clx-axis-v1 algorithm rolls lint evidence into axis scores."
sidebar_position: 5
tags: [lint, quality]
---

Apiome rolls catalog and MCP lint evidence into a multi-axis evaluation. The algorithm
identity shown in the UI is:

| Field | Value |
|-------|--------|
| Algorithm id | `clx-axis-v1` |
| Algorithm version | `3` (implementation revision) |

Source: `apiome-rest/src/app/axis_score.py` (`ALGORITHM_ID`, `ALGORITHM_VERSION`).

## What the axes mean

Axes include quality, protocol, security, supply chain, supportability, and compatibility.
An axis that has not been scanned is **not assessed** — that is not a clean score.

Composite scores are withheld until required coverage is met (v1: the `quality` axis). Every
assessed axis enters the composite at equal weight.

### Supportability, for data contracts

Since implementation revision `2` (FMT-5.5), the **supportability** axis is assessed for a
data contract — an item imported from ODCS or dbt — from the `governance` findings the
[data-contract rule pack](./lint-rules.md) produces: is there a reachable owner, a stated
service level, a freshness expectation, a documented retention window, a declared serving
location. Those findings score that axis instead of `quality`, so they are never counted
twice.

Every other subject is unchanged. A schema *language* — Avro, XSD, RELAX NG, CDDL, a Kafka
Connect schema — shares the `data_schema` paradigm but has no syntax in which to state an
owner or an SLA, so the pack does not run for it and its supportability axis stays **not
assessed**: a capability limit of the format is not a defect of the document. An API-paradigm
item is untouched in every respect, including its score, grade and report fingerprint.

### Security, for API descriptions

Since implementation revision `3` (ASP-1.3), the **security** axis is assessed for an
API-paradigm revision — an OpenAPI, Swagger, AsyncAPI or other API description — from the
`security`-category findings of its newest native lint run: the findings of the built-in
`security` rule pack. Before revision 3 the axis was assessed for MCP servers only and an API
revision always read *not assessed*, even when security findings existed.

The axis is a deterministic **0–100 security score** beside the A–F grade, computed from
published constants:

```text
score = 100 − Σ_rule min(cap, Σ_findings penalty(severity) × weight(rule))
```

clamped to 0 and rounded. The severity penalties and the per-rule cap are the same house
constants every Apiome score uses; the **weight** is new. It multiplies a rule's penalty
*before* the cap, so one `error` from a weight-2 rule costs the full 20 points of its cap at
once — a revision whose only finding is one such error scores exactly 80 and grades B. Every
other `security` rule weighs 1.0. The table below is generated from the code that scores, so
it cannot drift from what the server does.

<!-- security-score:begin -->
<!-- GENERATED BLOCK — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

#### Constants

| Constant | Value |
|---|---|
| `error` penalty | 10 |
| `warning` penalty | 4 |
| `info` penalty | 1 |
| Per-rule penalty cap | 20 |
| Default rule weight | 1.0 |
| Grade bands | A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, else F |

#### Published rule weights

| Rule | Weight | OWASP API | In the catalog |
|---|---|---|---|
| `a2a.apikey-in-query` | 1.0 | — | yes |
| `a2a.insecure-endpoint` | 1.0 | — | yes |
| `a2a.no-security` | 1.0 | — | yes |
| `a2a.security-undeclared-scheme` | 1.0 | — | yes |
| `a2a.unknown-scheme-type` | 1.0 | — | yes |
| `security.credentials-in-server-url` | 2.0 | — | reserved — the rule has not shipped yet |
| `security.pii-exposed-without-auth` | 2.0 | — | reserved — the rule has not shipped yet |
| `security.secret-in-document` | 2.0 | — | reserved — the rule has not shipped yet |
| `security.write-operation-missing-auth` | 2.0 | — | reserved — the rule has not shipped yet |

Every other `security` rule weighs 1.0.

#### OWASP API Security Top 10 (2023) categories

Reference: https://owasp.org/API-Security/editions/2023/en/0x11-t10/

| Id | Category | Rules in the catalog |
|---|---|---|
| API1 | [Broken object level authorization](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) | 0 |
| API2 | [Broken authentication](https://owasp.org/API-Security/editions/2023/en/0xa2-broken-authentication/) | 0 |
| API3 | [Broken object property level authorization](https://owasp.org/API-Security/editions/2023/en/0xa3-broken-object-property-level-authorization/) | 0 |
| API4 | [Unrestricted resource consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/) | 0 |
| API5 | [Broken function level authorization](https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/) | 0 |
| API6 | [Unrestricted access to sensitive business flows](https://owasp.org/API-Security/editions/2023/en/0xa6-unrestricted-access-to-sensitive-business-flows/) | 0 |
| API7 | [Server side request forgery](https://owasp.org/API-Security/editions/2023/en/0xa7-server-side-request-forgery/) | 0 |
| API8 | [Security misconfiguration](https://owasp.org/API-Security/editions/2023/en/0xa8-security-misconfiguration/) | 0 |
| API9 | [Improper inventory management](https://owasp.org/API-Security/editions/2023/en/0xa9-improper-inventory-management/) | 0 |
| API10 | [Unsafe consumption of APIs](https://owasp.org/API-Security/editions/2023/en/0xaa-unsafe-consumption-of-apis/) | 0 |

<!-- security-score:end -->

**When the axis is not assessed.** The axis is scored only when the lint report carries the
security pack's `security` category bar, which the pack publishes whenever it evaluates an
API-paradigm artifact. Three cases therefore read **not assessed**, never 100:

- no security pack evaluated the revision (it was scored before the pack existed, or the
  artifact is not an API description — a data contract, for instance);
- the [style guide](./lint-and-quality.md#style-guides-govern-every-lint-run) the revision was
  scored under **disables every rule of the pack** — the guide withdraws the bar, because a
  pack that never ran cannot vouch for anything;
- the stored evaluation predates revision 3 — it is re-evaluated the next time the revision
  is linted or imported.

**OWASP sub-scores.** Beside the headline, the axis stores one entry per OWASP API Security
Top 10 (2023) category (`API1` … `API10`): the same formula over the findings whose rule cites
that category, the finding count, and a **coverage** state. Coverage is `full` when at least
one rule citing the category evaluated for the revision and `none` when every such rule was
skipped for the format (or no rule cites the category yet) — a `none` category renders *not
assessed*, never 100. A rule that cites two categories counts in both. When the newest run
skipped some security rules for the revision's format, the axis is assessed but its coverage
is `partial`, and the skipped rule ids are stored with it.

**Where it surfaces.** `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint`
returns `securityScore` / `securityGrade` beside `score` / `grade`, and the versions list
(`GET /v1/versions/{tenant_slug}/{project_id}`) carries each revision's stored
`securityScore` / `securityGrade`, read from the newest persisted `clx-axis-v1` evaluation
exactly as `qualityScore` is read from the record — a project with 50 revisions issues zero
lint requests to render them. `GET /v1/lint/rules` publishes `weight` and `owasp` per rule,
and `GET /v1/lint/workspace/summary` splits every axis's assessed count by subject type, so
the posture workspace can say how many catalog subjects carry an assessed security axis. The
security axis of an MCP server is unchanged: its surface-lint security rules score it under
the plain formula, without weights or OWASP API sub-scores.

**Comparability.** The axis set, the equal composite weights and the composite formula did
not change, which is why the algorithm id stays `clx-axis-v1`. An evaluation stored before
revision 3 and one stored after are not directly comparable for an API revision's security
axis (and therefore its composite); the quality axis of every subject, and every axis of
every MCP server and data contract, is byte-identical across the bump. The external Spectral
OWASP ruleset the `spectral.oas` adapter can run (ASP-1.1) does **not** score the axis — its
findings are parity evidence, and scoring them as well would count one defect twice.

## Honesty guarantees

- Skipped rules (missing transcript, source, SBOM, or probe consent) never count as passes.
- An OWASP API category none of whose rules evaluated reads *not assessed*, never 100.
- Static trust-posture findings are **signals**, not proven exploits, until a consent-gated
  probe demonstrates exploitability ([MCP probes](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/mcp_probes.md)).

## Related documentation

- [Lint & quality](./lint-and-quality.md)
- [Scanner evaluation corpus](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/scanner_evaluation.md) (CLX-4.3)
- [MCP trust posture](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/mcp_trust_posture.md)
- Built-in schema rules: [Built-in lint rules](./lint-rules.md)
