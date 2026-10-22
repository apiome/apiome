---
title: "Import Zod schemas"
description: "Catalog the schemas a Zod module exports, with their validation constraints."
sidebar_position: 8.6
tags: [import, zod, typescript, schema]
---

Zod is where many TypeScript projects keep their runtime schema. A Zod schema carries the
validation rules an API description needs — lengths, patterns, formats, numeric bounds — which a
plain TypeScript type does not. Apiome imports a module's exported Zod schemas, with those rules,
as **schema types** in the catalog.

## What you can import

| You have | Import it as |
| --- | --- |
| One module that does `import { z } from 'zod'` and exports schemas | One file, or paste the source |
| Modules that import schemas from one another, with a root module | One archive with all the modules; the root is the module whose exports you want |

Only the root module's **exported** schemas become part of the catalog item. A schema another
module exports appears only when an exported schema refers to it.

Apiome reads the Zod 3 API (`zod` 3.x, or `zod/v3`). A module written against the Zod 4 entry
points (`zod/v4`, `zod/mini`) is refused with `FORMAT_VERSION_UNSUPPORTED`.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises a module that imports `zod` and exports schemas, and picks **Zod schemas** (`zod`). A
module of plain `interface` and `type` declarations goes to
[TypeScript types](./typescript-types-import.md) instead.

The schemas land in the [Catalog](./catalog.mdx) as a schemas-only item, named after the root
module's first exported object schema.

## How the module is read

A Zod schema is a value, so Apiome has to **run** the module to read it. It runs it in a sandbox:

- The module can read nothing outside Apiome's own toolchain, start no process and open no network
  connection.
- It sees an empty environment, so it cannot read the service's settings or secrets.
- Only `zod` and the modules in your upload can be imported.
- Importing the module and reading its schemas each have a **5-second** time limit. A module that
  loops forever fails with `INPUT_TIME_LIMIT`.

A module that needs anything else at import time — environment variables, a configuration file, a
network call — fails with `INPUT_SEMANTIC_INVALID`. Move that logic out of the schema module, or
import a module that only declares schemas.

## What each schema becomes

| Zod | Becomes |
| --- | --- |
| `z.object({ … })` | A record. `merge`, `extend`, `pick`, `omit`, `partial` and `required` are applied first. |
| `z.enum([…])`, `z.nativeEnum(…)` | An enum. |
| `z.union([…])`, `z.discriminatedUnion(…)` | A union. Inline object variants become records named after their discriminant, for example `Problem_validation`. |
| `z.intersection(a, b)` of objects | One record with the properties of both. |
| `z.array`, `z.set`, `z.tuple` | A list (`set` adds unique items; a tuple is bounded by its length). |
| `z.record`, `z.map` | A map. |
| A reference to another exported schema, including `z.lazy` recursion | A reference to that schema's type. |

Constraints are kept on the field:

| Zod | Constraint |
| --- | --- |
| `.min()`, `.max()`, `.length()` | Minimum and maximum length (strings) or item count (arrays and sets) |
| `.regex()`, `.startsWith()`, `.endsWith()`, `.includes()` | A pattern |
| `.email()`, `.url()`, `.uuid()`, `.datetime()`, `.date()`, `.time()` | A format |
| `.int()` | An integer type |
| `.gt()`, `.gte()`, `.lt()`, `.lte()`, `.positive()`, `.nonnegative()`, `.multipleOf()` | Numeric bounds |
| `.optional()`, `.nullable()`, `.nullish()` | A nullable field |
| `.default()` | The field's default value |
| `.describe()` | The description |

## What is declared, not imported

Some Zod constructs have no schema equivalent. Apiome lists each one in the import's coverage
ledger, under the schema's name, instead of dropping it silently:

- **Kept, with the rule listed:** `refine` and `superRefine`, `transform` (including `trim`,
  `toLowerCase` and `toUpperCase`), `preprocess`, `brand`, `pipe` and `z.coerce.*`. The schema they
  wrap is imported; the rule itself is not.
- **Left out:** `z.custom()`, `z.function()`, `z.promise()`, and schemas with no data meaning
  (`never`, `symbol`, `NaN`). Nothing is turned into `any`.
- A tuple's per-position types and a `catchall` schema are recorded on the type and listed too.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The module has a TypeScript syntax error, such as an unclosed call. |
| `INPUT_TRUNCATED` | The module ends in the middle of a schema. |
| `INPUT_SEMANTIC_INVALID` | The module exports no Zod schema, or it threw while it was being run (for example, it reads an environment variable). |
| `INPUT_TIME_LIMIT` | Running the module, or reading its schemas, took longer than the time limit. |
| `INPUT_REFERENCE_UNRESOLVED` | The module imports something other than `zod` and the modules in the upload. |
| `FORMAT_MISMATCH` | The module does not import `zod`; plain types belong to TypeScript types. |
| `FORMAT_VERSION_UNSUPPORTED` | The module imports the Zod 4 API (`zod/v4`, `zod/mini`). |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |

## What is inferred

On the catalog item, a schema Apiome names (an anonymous object or a generic instantiation) is **synthesized**. Those entities carry a badge with the evidence, and the
**Provenance** filter on the **Overview** tab narrows to them — see
[Declared, inferred and synthesized](./inference-provenance.mdx).

## Related

- [Import TypeScript types](./typescript-types-import.md): the same shapes, written as types.
- [Supported formats](./supported-formats.md#format-zod): what this importer reads.
- [Read a catalog item's format details](./catalog-format-details.md): where the coverage ledger
  lists what was declared.
- [Convert a catalog item to OpenAPI](./convert-to-openapi.md): turn the imported schemas into a
  Project's schemas, with their constraints.
