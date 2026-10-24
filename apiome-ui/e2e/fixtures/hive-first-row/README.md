# Frozen first-row fixtures (HIVE-13.3, #5616)

Unlike the other `hive-*` folders, nothing re-dumps these files. They are copies of the Catalog
table fixture (`hive-catalog/table.html`) at two points in history, kept so
`e2e/visual/first-row.spec.ts` can prove the first-row budget tells them apart:

| File | Taken from | First row at 1440 × 900 |
| --- | --- | --- |
| `catalog-pre-quiet-pass.html` | the parent of `6f709f0b3` — before HIVE-11.6 (#5602) | ≈ 609 px: fails the 360 px list budget |
| `catalog-quiet-pass.html` | `6f709f0b3` — HIVE-11.6 (#5602) as merged | ≈ 344 px: within it |

They are mounted against today's `globals.css`, so a class whose styles have since been retired
renders unstyled. Do not edit or re-dump them; if a stylesheet change ever moves either across the
budget, the spec will say so and the history is the thing to reconsider, not the copy.
