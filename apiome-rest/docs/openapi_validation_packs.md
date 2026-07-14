# OpenAPI validation packs (CLX-2.2)

> **Status:** Spectral / Vacuum / Redocly adapters + curated profiles + parity-selected
> default bulk runner — `src/app/openapi_validation_*.py`
> **Issue:** [#4852](https://github.com/apiome/apiome/issues/4852) · **Epic:** CLX-EPIC-2 (#4845)
> · **Depends on:** CLX-2.1 (#4851)

Native OpenAPI lint does not cover the full structural / `$ref` breadth of mature free
tooling. This pack ships curated Apiome **baseline**, **tenant_guide**, and **strict**
profiles for Spectral, Vacuum, and Redocly on the sandboxed external-linter SPI.

```
Style guide profile ──▶ curated ruleset / tenant overlay
        │
        ▼
 DEFAULT_BULK_RUNNER (spectral.oas) ──▶ RestrictedRunner (no network)
        │
        ▼
 SARIF / Spectral-JSON ──▶ envelope findings ──▶ lint_evidence_runs
```

## Profiles

| Profile | Meaning |
|---------|---------|
| `baseline` | Apiome recommended Spectral/Redocly configs under `rulesets/openapi/baseline/` |
| `strict` | Broader / error-forward configs under `rulesets/openapi/strict/` |
| `tenant_guide` | Baseline + Spectral overlay generated from the guide's GOV custom-rule DSL |

Selection is stored on `style_guides.external_lint_profile` (V170) and exposed on style-guide
CRUD as `externalLintProfile`. Discovery: `GET /v1/lint/external-adapters`.

## Default bulk runner

`DEFAULT_BULK_RUNNER` is **`spectral.oas`**. The choice is documented in
`tests/fixtures/openapi_validation_parity/parity_matrix.json` and is **parity-based**
(Spectral is the compatibility reference). Vacuum/Redocly remain available as secondary
adapters; Vacuum becomes eligible as the default only after equivalent enabled-rule output
is demonstrated on that corpus.

## Adapters

| Id | Tool | Output |
|----|------|--------|
| `spectral.oas` | `@stoplight/spectral-cli` | SARIF |
| `vacuum.oas` | `vacuum spectral-report` | Spectral JSON |
| `redocly.oas` | `@redocly/cli lint` | JSON |

Findings keep original rule IDs, locations, remediation links, and tool/adapter versions.
Multi-file local `$ref` trees are materialized into a scratch workspace; remote fetch is
disabled (Vacuum `--remote=false`) and the restricted runner uses the no-network sandbox.

## Facade

```python
from app.openapi_validation_pack import run_openapi_validation_pack

result = await run_openapi_validation_pack(
    document=spec,  # or files={...}
    profile="baseline",
)
evidence = result.to_evidence_run(subject_id=version_record_id)
```

Evidence is captured best-effort at live lint (`build_lint_report`) and import score capture.
Native OpenAPI scoring remains authoritative for policy grades.

## Spectral-compatible custom guides

GOV custom rules continue to use the Spectral-compatible subset DSL. Under `tenant_guide`,
those definitions are rendered into a Spectral overlay that extends the Apiome baseline —
full Spectral `extends:` imports are still rejected by the GOV validator (intentional).
