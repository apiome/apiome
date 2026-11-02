---
title: "Import a FlatBuffers or Cap'n Proto schema"
description: "Catalog FlatBuffers and Cap'n Proto schemas, versioned by field id."
sidebar_position: 47
tags: [import, flatbuffers, fbs, capnproto, capnp, binary, breaking-changes]
---

The **FlatBuffers** (`flatbuffers`) and **Cap'n Proto** (`capnproto`) importers read zero-copy
binary schemas into the [Catalog](./catalog.mdx). Tables, structs, unions and enums become types,
and a Cap'n Proto `interface` becomes a service with one operation per method. You can then search,
version, diff, lint and convert them like any other catalog item.

## Import it

Import the schema like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **FlatBuffers** or **Cap'n Proto**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI:

```bash
apiome import flatbuffers ./monsters.fbs
apiome import capnproto ./addressbook.capnp
```

Upload a `.zip`, `.tar.gz` or `.tar` when the schema `include`s or `import`s other files. The CLI's
test fixtures, in `apiome-cli/tests/fixtures/`, are a quick way to try either format:
`monsters-flatbuffers.fbs` and `addressbook-capnproto.capnp`.

## Breaking changes between versions

Both formats identify a field on the wire by a **number**, not its name, so a new version of the
catalog item is compared by that number.

### FlatBuffers

A table field's number is its `(id: N)`, or its position among the table's fields when the table
writes no ids (a union field takes two). A field is never removed: it is marked `(deprecated)`, so
its id stays taken. A `struct` is a fixed layout with no ids.

| Change | Severity | Rule |
| --- | --- | --- |
| A field renamed, id and type unchanged | Dangerous: binary buffers still read; JSON and generated code do not | `fbs.field-renamed` |
| A field id reused for a field of another type | Breaking | `fbs.field-id-reused` |
| A field moved to another id, for example because a field was inserted before it | Breaking | `fbs.field-id-changed` |
| A field marked `(deprecated)` | Safe | `fbs.field-deprecated` |
| A field removed without `(deprecated)` | Breaking | `fbs.field-removed` |
| A field added at a new id | Safe | `fbs.field-added` |
| A field's default changed | Dangerous: buffers that omit the field now read another value | `fbs.default-changed` |
| Any change to a `struct` field | Breaking | `fbs.struct-changed` |
| An enum value renumbered or removed | Breaking | `fbs.enum-value-changed`, `fbs.enum-value-removed` |
| A union member removed or reordered | Breaking | `fbs.union-member-removed` |

### Cap'n Proto

Every struct field, interface method and enumerant has an `@N` ordinal, and names never reach the
wire. A member can be renamed freely and added at the next ordinal, but never removed or
renumbered: keep an obsolete member and rename it instead.

| Change | Severity | Rule |
| --- | --- | --- |
| A field or method renamed, ordinal and type unchanged | Safe | `capnp.field-renamed`, `capnp.method-renamed` |
| An ordinal reused for a member of another type or signature | Breaking | `capnp.ordinal-reused` |
| A member moved to another ordinal | Breaking | `capnp.ordinal-changed` |
| A field or method removed | Breaking | `capnp.field-removed`, `capnp.method-removed` |
| A field or method added at a new ordinal | Safe | `capnp.field-added`, `capnp.method-added` |
| An enumerant renumbered or removed | Breaking | `capnp.enum-value-changed`, `capnp.enum-value-removed` |

Every other change (a removed type, a changed method result) is graded by the standard rules.

## Lint rules

On top of the common rules, every FlatBuffers item is checked by the `flatbuffers` pack and every
Cap'n Proto item by the `capnproto` pack:

| Rule | Severity | Checks |
| --- | --- | --- |
| [`flatbuffers.root-type-declared`](../build/lint-rules.md#flatbuffers-root-type-declared) | Info | A schema with tables declares its `root_type`. |
| [`flatbuffers.namespace-declared`](../build/lint-rules.md#flatbuffers-namespace-declared) | Info | The schema declares a `namespace`. |
| [`flatbuffers.unique-field-ids`](../build/lint-rules.md#flatbuffers-unique-field-ids) | Error | No two fields of a table, or a field and a deprecated slot, share an id. |
| [`flatbuffers.explicit-ids-all-or-none`](../build/lint-rules.md#flatbuffers-explicit-ids-all-or-none) | Error | A table declares `(id: N)` on every field or on none. |
| [`capnproto.file-id-declared`](../build/lint-rules.md#capnproto-file-id-declared) | Error | The file declares its `@0x…;` id (`capnp id` generates one). |
| [`capnproto.unique-ordinals`](../build/lint-rules.md#capnproto-unique-ordinals) | Error | No two members of a struct, interface or enum share an ordinal. |
| [`capnproto.contiguous-ordinals`](../build/lint-rules.md#capnproto-contiguous-ordinals) | Error | Ordinals run from `@0` without a gap. |

The error rules are the ones `flatc` and the Cap'n Proto compiler enforce, so a schema they flag
does not compile.

## Related

- [Supported formats](./supported-formats.md): version coverage and export support
- [Lint rules](../build/lint-rules.md#pack-flatbuffers): the `flatbuffers` and `capnproto` packs
