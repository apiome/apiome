# Change taxonomy & classifier (CTG-1.1)

> **Status:** OpenAPI document classifier — `src/app/change_taxonomy.py`  
> **Issues:** [#4467](https://github.com/apiome/apiome/issues/4467) (taxonomy) · [#4470](https://github.com/apiome/apiome/issues/4470) (regression corpus)  
> **Epic:** CTG-EPIC-1 (#4459)

Classifies every change between two OpenAPI documents as **breaking**, **non-breaking**, or **docs-only**. Each classified change carries a stable **rule id**, a **JSON Pointer**, and **before/after** values. Unknown enumerator kinds fail safe to **breaking** with `unclassified=True`.

This is distinct from the canonical [`ModelDiff`](./diff_spi.md) / [`breaking_change`](./breaking_change_spi.md) SPI (which scrub documentation and use `safe` / `dangerous` / `breaking`). CTG needs docs-only severity and OpenAPI JSON Pointers for CI gates and changelogs.

```
 base OpenAPI ──┐
                ├─ enumerate_openapi_changes ─▶ RawChange[] ─▶ rule registry ─▶ ClassifiedDiff
 head OpenAPI ──┘                                      │
                                                       └─ no match → ctg.unclassified (breaking)
```

## Public API

```python
from app.change_taxonomy import classify_openapi_changes, override_severity

result = classify_openapi_changes(base_doc, head_doc)
# result.changes: list[ClassifiedChange]
# result.counts:  {breaking, non-breaking, docs-only, unclassified, total}
# result.max_severity: worst severity or None when empty
```

Optional call-site severity overrides (GOV style-guide hook):

```python
classify_openapi_changes(base, head, overrides={"ctg.path_removed": "non-breaking"})
# or persist via override_severity("ctg.path_removed", "non-breaking")
```

## Severities

| Severity | Meaning |
|----------|---------|
| `breaking` | Removes or narrows surface consumers may depend on |
| `non-breaking` | Additive / widening optional changes |
| `docs-only` | Description, summary, example, externalDocs, tag metadata |

Worst-of order: `docs-only` < `non-breaking` < `breaking`.

## Default rule catalog

| Rule id | Change kind | Default severity |
|---------|-------------|------------------|
| `ctg.path_removed` | `path_removed` | breaking |
| `ctg.operation_removed` | `operation_removed` | breaking |
| `ctg.response_removed` | `response_removed` | breaking |
| `ctg.property_removed` | `property_removed` | breaking |
| `ctg.type_narrowed` | `type_narrowed` | breaking |
| `ctg.optional_to_required` | `optional_to_required` | breaking |
| `ctg.required_param_added` | `required_param_added` | breaking |
| `ctg.enum_value_removed` | `enum_value_removed` | breaking |
| `ctg.security_tightened` | `security_tightened` | breaking |
| `ctg.server_removed` | `server_removed` | breaking |
| `ctg.path_added` | `path_added` | non-breaking |
| `ctg.operation_added` | `operation_added` | non-breaking |
| `ctg.response_added` | `response_added` | non-breaking |
| `ctg.property_added` | `property_added` | non-breaking |
| `ctg.optional_param_added` | `optional_param_added` | non-breaking |
| `ctg.server_added` | `server_added` | non-breaking |
| `ctg.enum_value_added` | `enum_value_added` | non-breaking |
| `ctg.security_relaxed` | `security_relaxed` | non-breaking |
| `ctg.docs_description` | `docs_description` | docs-only |
| `ctg.docs_summary` | `docs_summary` | docs-only |
| `ctg.docs_example` | `docs_example` | docs-only |
| `ctg.docs_external_docs` | `docs_external_docs` | docs-only |
| `ctg.docs_tag` | `docs_tag` | docs-only |
| `ctg.unclassified` | *(no match)* | breaking + `unclassified` |

New rules: `register_rule(TaxonomyRule(...))` — identical re-register is a no-op; conflicting metadata raises.

## Regression corpus

Fixtures live under `tests/fixtures/diff/<case>/` (`base.yaml`, `head.yaml`, `expected.json`).  
`tests/test_change_taxonomy_corpus.py` asserts exact golden match and that every default rule appears in at least one case.

## Modules

| Module | Role |
|--------|------|
| `app.change_taxonomy` | Public types + `classify_openapi_changes` |
| `app.change_taxonomy_enum` | OpenAPI walk → `RawChange` |
| `app.change_taxonomy_rules` | Rule registry + defaults |
