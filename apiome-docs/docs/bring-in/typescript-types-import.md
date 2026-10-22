---
title: "Import TypeScript types"
description: "Catalog the interfaces, type aliases and enums a TypeScript module exports."
sidebar_position: 8.5
tags: [import, typescript, schema]
---

Many teams describe their data in a `types.ts` and nowhere else. Apiome reads the exported
`interface`, `type` and `enum` declarations of a TypeScript module and catalogs them as **schema
types**, the same way it catalogs a JSON Schema or an Avro file. The module is read by the
TypeScript compiler itself, so a type means what `tsc` says it means.

## What you can import

| You have | Import it as |
| --- | --- |
| One module of declarations (`types.ts`, `models.d.ts`) | One file, or paste the source |
| Modules that `import type` from one another, with an index that re-exports them | One archive with all the modules; the index is the root |
| A published package's declaration file (`index.d.ts`) | One file |

Only what the root module **exports** becomes part of the catalog item. A declaration that is not
exported appears only when an exported type refers to it.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises a module of exported type declarations and picks **TypeScript types**
(`typescript-types`). For a set of modules, upload one archive; the root is the module the others
are re-exported from (usually `index.ts`).

The types land in the [Catalog](./catalog.mdx) as a schemas-only item. The item is named after the
root module's first exported interface, so the same module pasted or uploaded becomes the same
item.

## What each declaration becomes

| TypeScript | Becomes |
| --- | --- |
| `interface Order { … }` | A record. `extends` is flattened: the parents' properties come first and the child's own properties override them. |
| `type Status = 'new' \| 'paid'` | An enum whose values are the literals. A literal union written inline on a property stays a string with those allowed values. |
| `type Event = Placed \| Shipped`, or a union of object literals | A union. Inline object variants become records named after their discriminant, for example `Shape_circle`. |
| `type Audited = Record & { auditedBy: string }` | One record with the properties of every part. |
| `enum Role { … }`, `const enum` | An enum, with each member's value. |
| `string[]`, `Array<T>`, `ReadonlyArray<T>`, `Set<T>` | A list (`Set` adds unique items). |
| `[id: string, count: number]` | A list bounded by the tuple's length. Each position's type and label is recorded on the type. |
| `Record<K, V>`, `Map<K, V>`, or an object that is only `[key: string]: V` | A map. |
| `Date` | A string with the `date-time` format. |
| `Pick`, `Omit`, `Partial`, `Required`, `Readonly`, `Order['status']`, `keyof Order` | The shape the compiler computes for them. |

An optional property (`note?: string`) and a property that allows `null` or `undefined` are both
**nullable**. Whether the property was optional or `readonly` is kept on the field.

### Generics

A generic type is modelled where it is used with concrete type arguments. `type OrderPage =
Page<Order>` becomes a record called `OrderPage` with `Page`'s properties and `T` replaced by
`Order`. A property typed `Paginated<Customer>` gets its own record, `Paginated_Customer`. A generic
that is never used with concrete arguments is not modelled; it is listed as a parsing limit.

## What is declared, not imported

Some TypeScript describes computation or behaviour rather than data. Apiome never turns these into
`any`. It leaves the declaration (or the single property) out of the catalog item and lists it in
the import's coverage ledger, under the declaration's name:

- conditional types (`T extends U ? X : Y`), mapped types (`{ [K in keyof T]: … }`) and
  template-literal types;
- a generic that is never instantiated, and a type parameter with no argument;
- an interface declared more than once (declaration merging), and any property that refers to it;
- function, constructor and method signatures;
- properties keyed by a symbol, such as `[brand]: true`;
- `typeof` queries and library types with no data shape, such as `Promise`.

Two things are imported with a detail kept aside: a tuple's per-position types, and an index
signature that sits beside named properties. Both are recorded on the type and listed in the
ledger.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The module has a TypeScript syntax error, such as a missing `}`. |
| `INPUT_TRUNCATED` | The module ends in the middle of a declaration. |
| `INPUT_SEMANTIC_INVALID` | The module exports no interface, type alias or enum. |
| `INPUT_REFERENCE_UNRESOLVED` | An exported type refers to a type that no module in the upload declares, for example one imported from a module you did not include. Add that module, or upload the modules together as an archive. |
| `FORMAT_MISMATCH` | The module imports a schema library such as Zod, so its schemas are values rather than type declarations. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |

## Related

- [Supported formats](./supported-formats.md#format-typescript-types): what this importer reads,
  and the TypeScript version it uses.
- [Read a catalog item's format details](./catalog-format-details.md): where the coverage ledger
  lists what was declared.
- [Convert a catalog item to OpenAPI](./convert-to-openapi.md): turn the imported types into a
  Project's schemas.
