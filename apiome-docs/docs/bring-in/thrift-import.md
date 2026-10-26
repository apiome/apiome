---
title: "Import an Apache Thrift API"
description: "Catalog Thrift IDL, including multi-file sets joined by include."
sidebar_position: 40
tags: [import, thrift, rpc, include, breaking-changes, lint]
---

The **Thrift** importer (`thrift`) reads Apache Thrift IDL (`.thrift`) into the
[Catalog](./catalog.mdx). Structs, unions, exceptions and enums become types, and each service
method becomes an operation. You can then search, version, diff, lint and convert it like any other
catalog item.

## Import it

Import the IDL like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **Thrift**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI:

```bash
apiome import thrift ./orders.thrift
apiome import thrift ./orders-idl.zip
```

- **One file.** Upload, paste or link the `.thrift` file.
- **A file set.** Upload a `.zip`, `.tar.gz` or `.tar` that holds the root document and every file
  it includes.

## File sets and `include`

A Thrift API is often split across files. The root includes the others and refers to their
definitions with the file name as a prefix:

```thrift
include "shared.thrift"
include "errors.thrift"

service OrderService extends shared.BaseService {
  Order getOrder(1: OrderId id) throws (1: errors.NotFound notFound),
}
```

When you import a set, Apiome reads the root and every file it includes, at any depth:

- **Included types.** Each file's types join the catalog item under that file's own `namespace`.
  An included file that declares no namespace uses its file name instead, such as `common.Money`.
- **Qualified names.** A field, parameter, return type or exception written `shared.Money` links to
  the `Money` that `shared.thrift` defines. A `typedef` in an included file, such as `shared.Amount`,
  resolves to its underlying type.
- **Every service.** Services from included files are cataloged too. A service that `extends`
  another records the base service in `thrift_extends`.
- **Where files are found.** An `include` path is read relative to the file that includes it, and
  then relative to the root's folder, as the Thrift compiler's `-I` search path does.
- **Source files.** The catalog item lists the files it was built from in `thrift_source_files`.

A single file that includes others still imports on its own, but the included definitions are
missing and `shared.Money` stays an unresolved name. Upload the set as an archive to resolve them.

### When the import refuses a set

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_REFERENCE_UNRESOLVED` | An `include` names a file that is not in the upload. | Add the file to the archive. |
| `INPUT_REFERENCE_UNRESOLVED` | An `include` is an absolute path, a URL, or a `../` path that leaves the upload. Such files are never read. | Copy the file into the archive and include it by a relative path. |
| `INPUT_SEMANTIC_INVALID` | Files include each other in a cycle. The message names the cycle. | Remove one of the includes. |
| `INPUT_ARCHIVE_INVALID` | The archive has no root document. | Put the root `.thrift` file in the archive. |

## Breaking changes between versions

Thrift identifies a field on the wire by its **field id**, not its name, so a new version of a
Thrift catalog item is compared by field id:

| Change | Severity | Rule |
| --- | --- | --- |
| A field renamed, id and type unchanged | Dangerous: the binary and compact protocols still read it; JSON and generated code do not | `thrift.field-renamed` |
| A field id reused for a field of another type | Breaking | `thrift.field-id-reused` |
| A field moved to another id | Breaking | `thrift.field-id-changed` |
| A `required` field added or removed | Breaking | `thrift.required-field-added`, `thrift.required-field-removed` |
| An optional field removed (its id not reused) | Dangerous: never reuse the id | `thrift.optional-field-removed` |
| An optional field added | Safe | `thrift.optional-field-added` |
| An optional field made `required` | Breaking | `thrift.made-required` |
| A `required` field made optional | Dangerous | `thrift.made-optional` |

Every other change (a removed service or method, a changed return type) is graded by the standard
rules.

## Lint rules

On top of the common rules, every Thrift catalog item is checked by the `thrift` pack:

| Rule | Severity | Checks |
| --- | --- | --- |
| [`thrift.namespace-declared`](../build/lint-rules.md#thrift-namespace-declared) | Info | The document declares a `namespace`. |
| [`thrift.field-no-required`](../build/lint-rules.md#thrift-field-no-required) | Warning | No field is `required`, a choice that can never be undone. |
| [`thrift.unique-field-ids`](../build/lint-rules.md#thrift-unique-field-ids) | Error | No two fields, parameters or exceptions share an id. |
| [`thrift.enum-explicit-values`](../build/lint-rules.md#thrift-enum-explicit-values) | Warning | Every enum value has an explicit number. |
| [`thrift.oneway-void`](../build/lint-rules.md#thrift-oneway-void) | Error | A `oneway` method returns `void` and declares no `throws`. |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): Thrift's coverage and export support
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
