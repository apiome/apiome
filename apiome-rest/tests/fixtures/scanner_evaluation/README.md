# Scanner-evaluation corpus

Reproducible fixtures behind the scanner claims (CLX-4.3, #4861) and the auto-fix guarantees
(GVM-3.5, #5873). `manifest.json` indexes every fixture; the runners live in
`src/app/scanner_evaluation_corpus.py`. See `docs/scanner_evaluation.md`.

## Fix fixtures (`fix/<rule id>/fixture.json`)

Each fixable lint rule has a one-defect fixture: the `before` document, the expected `plan`
(RFC 6902 operations) and the expected `after` document. CI gates (`tests/test_scanner_fix_corpus.py`):

1. after the fix the rule is clean;
2. the finding set outside the rule is unchanged;
3. planning and applying twice is byte-stable;
4. the classified diff of the fix is non-breaking;
5. a rule flagged `fixable` without a fixture fails the build.

Adding a fixable rule means adding `fix/<rule id>/fixture.json`, a manifest entry
(`"kind": "fix"`) and regenerating this table:

```
uv run python scripts/generate_fix_corpus_readme.py
```

<!-- fixable-rules:begin -->
| Rule | Fix class | On by default | Fixture | What the fix does |
|------|-----------|---------------|---------|-------------------|
| `naming.operation-id-camel-case` | rename | yes | `fix/naming.operation-id-camel-case/` | Re-cases the operationId to camelCase when no link refers to it and the new id is free. |
| `naming.schema-pascal-case` | rename | no | `fix/naming.schema-pascal-case/` | Renames the schema to PascalCase and rewrites every reference to it. Changes generated type names; never applied unless opted in. |
| `naming.tag-case-mismatch` | rename | yes | `fix/naming.tag-case-mismatch/` | Replaces the tag use with the spelling of its declaration. |
| `structure.boolean-exclusive-bound` | structural | yes | `fix/structure.boolean-exclusive-bound/` | Moves the bound's number onto the exclusive keyword, or drops a flag that sets no bound. |
| `structure.duplicate-tag` | removal | yes | `fix/structure.duplicate-tag/` | Removes a repeated tag declaration that adds nothing to the first. |
| `structure.empty-required` | removal | yes | `fix/structure.empty-required/` | Removes the empty required list. |
| `structure.nullable-keyword` | structural | yes | `fix/structure.nullable-keyword/` | Adds null to the schema's type (and enum) and removes nullable. |
| `structure.operation-missing-operation-id` | fill-in | yes | `fix/structure.operation-missing-operation-id/` | Adds an operationId built from the HTTP method and the path by a configurable template. |
| `structure.operation-missing-tags` | fill-in | no | `fix/structure.operation-missing-tags/` | Adds a tag named after the first path segment. Off unless opted in. |
| `structure.schema-example-keyword` | structural | yes | `fix/structure.schema-example-keyword/` | Moves example into a one-item examples array. |
| `structure.server-url-scheme-case` | structural | yes | `fix/structure.server-url-scheme-case/` | Lower-cases the scheme of the server URL. |
| `structure.server-url-trailing-slash` | structural | yes | `fix/structure.server-url-trailing-slash/` | Removes the trailing slash from the server URL. |
| `structure.unused-component` | removal | yes | `fix/structure.unused-component/` | Removes the unreferenced component. |
<!-- fixable-rules:end -->
