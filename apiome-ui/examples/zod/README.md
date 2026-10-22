# Zod schemas — `zod`

Fixtures for **FMT-8.2** ([#5463](https://github.com/apiome/apiome/issues/5463)). Zod is where most
TypeScript projects put their *runtime* schema, and unlike a bare type it carries validation
constraints — min/max, regex, email, uuid — which are exactly the constraints an API description needs
and a plain type lacks. Owned by the `zod` adapter (`apiome-rest/src/app/zod_import_source.py`); valid
entries are pinned by golden snapshots under `apiome-rest/tests/golden/corpus/zod/`.

**Detection markers.** An `import { z } from 'zod'` (or `zod/v4`) plus exported `z.object(...)` /
`z.enum(...)` / `z.discriminatedUnion(...)` values. A module with types but no Zod values belongs to
`typescript-types/` — see `negative/04`.

**Constraint mapping.** `min`/`max`/`length` → string length or array bounds; `regex` → pattern;
`email`/`url`/`uuid`/`datetime` → format; `int`/`positive`/`gte`/`multipleOf` → numeric constraints;
`optional`/`nullable`/`default` → optionality; `strict`/`passthrough`/`catchall` → additional
properties; `discriminatedUnion` → a discriminated canonical union.

**Declared limits.** `refine`, `superRefine`, `transform`, `preprocess`, `brand`, `pipe`, `custom`,
`z.function()` and `z.promise()` have no JSON Schema analogue and must be **declared limits, not
silently dropped**. `04-stress-constraint-coverage.ts` is split along exactly that line.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-schema.ts` | minimal | One object, two fields. |
| `02-typical-order-schemas.ts` | typical | Regex, bounds, enum with a default, array cardinality, `pick`, `z.infer`. |
| `03-modules-set/` | multi-file | Three modules composing schemas across imports. |
| `04-stress-constraint-coverage.ts` | stress | Every string/number/collection constraint, object modifiers (`strict`, `passthrough`, `catchall`, `merge`, `extend`, `partial`), discriminated unions, `nativeEnum` — then the whole declared-limit set. |
| `05-real-world-api-validation.ts` | real-world | A service's request/response validation module: shared value schemas, coerced query parameters, a problem-details discriminated union. |
| `06-typical-recursive-and-lazy.ts` | typical | `z.lazy` recursion — a category tree, a JSON value union, a comment thread. |
| `07-composition-schema-reuse.ts` | composition | `merge`/`extend`/`pick`/`omit`/`partial`, a discriminated union over composed schemas, a schema factory. |
| `negative/` | — | Unclosed call, a module whose schemas are all private, truncation, a **plain TypeScript types** module, UTF-16, and a module that **throws on import**. |

**Execution boundary.** This adapter evaluates user code. The extractor
(`apiome-rest/toolchain/zod-extract.mjs`) runs it under Node's permission model (no file outside the
toolchain, no child process), with no network and an empty environment, inside a time budget.
`negative/06` proves a throwing module fails the job cleanly — it reads `process.env`, which the
sandbox does not provide — and an infinite loop fails within budget the same way
(`INPUT_TIME_LIMIT`; covered by `tests/test_zod_import_source.py`). Modules written against the Zod 4
entry points (`zod/v4`, `zod/mini`) are declined with `FORMAT_VERSION_UNSUPPORTED`.
