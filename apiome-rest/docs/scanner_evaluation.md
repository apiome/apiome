# Scanner evaluation — transparent rules and corpus (CLX-4.3)

> **Status:** foundational corpus and transparency catalog published  
> **Issue:** [#4861](https://github.com/apiome/apiome/issues/4861) ·
> **Epic:** CLX-EPIC-4 (#4847)

A claim to be a serious linter needs transparent rules, a reproducible fixture corpus,
differential tests before release, honest documentation of unassessed coverage, and a
published policy for retiring scanners.

## Rule transparency

Every **blocking** (`error`) rule across schema lint, MCP surface lint, MCP conformance,
and MCP trust posture carries:

| Field | Meaning |
|-------|---------|
| Stable `ruleId` | Exact string findings emit |
| `reference` | Normative / advisory URL |
| `rationale` | Why the rule exists |
| `remediation` | How to clear the finding |
| `falsePositiveGuidance` | When a hit may be noise |
| `fixtureId` | Corpus fixture that demonstrates the rule |
| `scanModes` / evidence requirements | What must be present to evaluate the rule |

Source of truth: `src/app/scanner_rule_transparency.py` (`TRANSPARENCY_CATALOG_REVISION`).
Catalog APIs enrich descriptors:

- `GET /v1/lint/rules`
- `GET /v1/mcp/lint/rules`
- `GET /v1/mcp/conformance/rules`
- `GET /v1/mcp/trust-posture/rules`

Generated human docs: `docs/guide/lint-rules.md`, `docs/guide/mcp-*-rules.md`
(`uv run python scripts/generate_lint_rule_docs.py`).

## Corpus layout

```
tests/fixtures/scanner_evaluation/
  manifest.json
  mcp/safe/…                  # no blocking findings
  mcp/unsafe/surface/…        # MCP surface lint defects
  mcp/unsafe/conformance/…  # protocol MUST violations
  mcp/unsafe/owasp/…          # OWASP MCP Top 10 examples
  mcp/unsafe/toolbench/…      # ToolBench-style usability defects
  catalog/…                   # Arazzo / compatibility / multi-format pointers
```

Runners: `src/app/scanner_evaluation_corpus.py`. Tests:
`tests/test_scanner_evaluation_corpus.py` and `tests/test_scanner_rule_transparency.py`.

### Updating scanners (differential release gate)

Before merging scanner / rule changes:

1. Run `pytest tests/test_scanner_evaluation_corpus.py tests/test_scanner_rule_transparency.py`
2. If findings change intentionally, update `manifest.json` `expected_blocking_rule_ids`
   (and transparency metadata / fixtures) in the same PR
3. Do not remove fixtures that document OWASP / ToolBench coverage without replacement

## Unassessed coverage

Unscanned ≠ clean. Trust-posture and conformance engines report `skippedRules` when required
evidence (source, SBOM, transcript, probe) is absent. Axis evaluations leave axes
`not_assessed` until a scanner runs — see [mcp_trust_posture.md](./mcp_trust_posture.md) and
[axis-score guide](../../docs/guide/axis-score.md).

## Dynamic-scan consent risks

Probe profiles that exercise live servers require explicit consent, isolation, and kill
switches. Dynamic findings are never inferred from static patterns alone. See
[mcp_probes.md](./mcp_probes.md). Displayed algorithm versions link to the axis-score guide;
never treat a static signal as a proven exploit without probe evidence.

## Adapter deprecation policy

External / adapted scanners (Spectral, Vacuum, Redocly, Buf, GraphQL ESLint, oasdiff, …):

1. **Parity-selected defaults stay** until another adapter demonstrates equivalent findings
   on the evaluation corpus (and any format-specific parity matrix).
2. **Secondary adapters** remain available but must be labeled as such in
   [format_lint_capabilities.md](./format_lint_capabilities.md).
3. **Deprecation** requires: CHANGELOG notice, matrix/docs callout, and at least one
   **minor version** of dual support.
4. **Removal** only after the differential corpus stays green without that adapter and
   docs/CHANGELOG record the sunset.

## Soft performance budget

The foundational corpus pass has a soft wall-clock budget (`CORPUS_SOFT_BUDGET_SECONDS`)
to catch gross regressions. Published performance leaderboards remain post-v1
(epic MVP: benchmark publication continues after v1).
