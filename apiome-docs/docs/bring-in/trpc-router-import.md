---
title: "Import a tRPC router"
description: "Catalog a tRPC router's procedures as query, mutation and subscription operations."
sidebar_position: 8.7
tags: [import, trpc, typescript, rpc, zod]
---

tRPC has no IDL: the API contract exists only as the router in your TypeScript code. Apiome reads
that router and catalogs every procedure as an **operation**, with its input and output schemas,
so a tRPC API can be searched, diffed and converted like any other.

## What you can import

| You have | Import it as |
| --- | --- |
| One module that does `initTRPC` and exports a router (`export const appRouter = t.router({ … })`) | One file, or paste the source |
| An app router that merges feature routers from other modules, with schemas in a shared module | One archive with all the modules; the root is the module that exports the app router |

Apiome reads routers built with `@trpc/server` 10 or 11, whose inputs and outputs are Zod 3 schemas.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises a module that imports `@trpc/server` and builds a router, and picks **tRPC router**
(`trpc`). A module of plain Zod schemas goes to [Zod schemas](./zod-schema-import.md) instead.

The router lands in the [Catalog](./catalog.mdx) as an `rpc` item, named after the exported router.

Like a Zod module, a router only exists once its code has run, so Apiome runs the module in the same
sandbox as [Zod import](./zod-schema-import.md#how-the-module-is-read): no file access, no network,
an empty environment and a time limit. Only `@trpc/server`, `zod` and the modules in your upload
can be imported. Apiome never calls a procedure, so resolver code, the errors it throws and the
context your middleware builds are not read.

## What each part becomes

| tRPC | Becomes |
| --- | --- |
| `.query()` | A **query** operation |
| `.mutation()` | A **mutation** operation |
| `.subscription()` | A **subscription** operation (server streaming) |
| The procedure's path (`invoice.list`) | The operation's name and path; its key is the router path, for example `appRouter.invoice.list` |
| A nested `t.router({ … })` | A group of operations under its parent, three or more levels deep if you nest that far |
| `.input(schema)` | The request payload. Several chained `.input()` calls are merged into one, as tRPC merges them. |
| `.output(schema)` | The response payload |
| `.meta({ … })` | Kept on the operation |

Inputs and outputs are read the same way as [Zod schemas](./zod-schema-import.md#what-each-schema-becomes),
with all their constraints. A schema that your modules export by name — `Order`, `Money` — becomes a
type with that name, shared by every procedure that uses it. A schema written inline becomes a type
named after the procedure, for example `InvoiceListInput` and `InvoiceListOutput`.

## What is declared, not imported

Apiome lists these in the import's coverage ledger instead of guessing:

- **A hand-written validator.** `.input((raw) => …)` is a function, not a schema, so there is nothing
  to read. The operation is imported without a request payload, rather than with an empty one.
- **A lazily loaded router** (`lazy(() => import('./billing'))`). Its procedures are not known until
  it is first called.
- Everything [Zod import declares](./zod-schema-import.md#what-is-declared-not-imported) — `refine`,
  `transform`, `brand` and the rest — inside a procedure's schemas.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The module exports no router, the router has no procedures, no procedure has a Zod input or output schema, or the module threw while it was being run. |
| `INPUT_MALFORMED` | The module has a TypeScript syntax error, such as an unclosed `t.router({`. |
| `INPUT_TRUNCATED` | The module ends in the middle of a procedure. |
| `INPUT_TIME_LIMIT` | Running the module took longer than the time limit. |
| `INPUT_REFERENCE_UNRESOLVED` | The module imports something other than `@trpc/server`, `zod` and the modules in the upload. |
| `FORMAT_MISMATCH` | The module does not import `@trpc/server`. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |

## What is inferred

On the catalog item, the type that holds a procedure's inline input or output (`InvoiceListInput`) is **synthesized**. Those entities carry a badge with the evidence, and the
**Provenance** filter on the **Overview** tab narrows to them — see
[Declared, inferred and synthesized](./inference-provenance.mdx).

## Related

- [Import Zod schemas](./zod-schema-import.md): how procedure inputs and outputs are read.
- [Supported formats](./supported-formats.md#format-trpc): what this importer reads.
- [Read a catalog item's format details](./catalog-format-details.md): where the coverage ledger
  lists what was declared.
